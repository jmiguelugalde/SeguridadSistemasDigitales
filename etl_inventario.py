# etl_inventario.py
import os, sys, json, uuid, time, unicodedata, glob, logging
from pathlib import Path
from datetime import datetime
import polars as pl
from sqlalchemy import create_engine
from sqlalchemy.engine.url import URL
from dotenv import load_dotenv
import yaml
from typing import Optional, List, Any, Set
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

BASE = Path("C:\\Data\\ProyectoICiberseguridad")

def init_logger(base_dir: Path) -> logging.Logger:
    log_dir = base_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("etl")
    logger.setLevel(logging.INFO)
    # Evitar handlers duplicados si se re-ejecuta
    if logger.handlers:
        return logger

    # Formato JSON simple por línea
    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            payload = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "msg": record.getMessage(),
            }
            # Permite pasar dicts con extra={"event":..., "data":...}
            for k in ("event", "data", "correlation_id"):
                if hasattr(record, k):
                    payload[k] = getattr(record, k)
            return json.dumps(payload, ensure_ascii=False)

    formatter = JsonFormatter()

    # Archivo rotativo (5 MB, 5 backups)
    fh = RotatingFileHandler(log_dir / "etl.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Consola
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    return logger

def load_config() -> dict:
    """
    Carga configs/config.yaml si existe. Retorna dict con defaults seguros
    para las claves usadas por main(): sources, load, security, audit.
    """
    base_dir = Path(__file__).parent
    cfg_path = base_dir / "configs" / "config.yaml"
    cfg: dict = {}

    if cfg_path.exists():
        with cfg_path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

    # Defaults mínimos
    cfg.setdefault("sources", {})
    cfg["sources"].setdefault("base_folder", str(base_dir))
    cfg["sources"].setdefault("discover_patterns", ["*.xlsx", "*.csv"])

    cfg.setdefault("load", {})
    cfg["load"].setdefault("type", "mysql")
    cfg["load"].setdefault("table", "dw_inventario")
    cfg["load"].setdefault("parquet_out", str(base_dir / "data_curated" / "inventario_curado.parquet"))

    cfg.setdefault("security", {})
    cfg.setdefault("audit", {"print_json_log": True})

    return cfg

def _persist_audit(base_dir: Path, audit_dict: dict) -> None:
    """
    Persiste un archivo JSON con el resumen de auditoría de la corrida.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = base_dir / "logs" / f"audit_{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(audit_dict, f, ensure_ascii=False, indent=2)

def normalize_text(s: str):
    if s is None:
        return None
    s = " ".join(str(s).split())
    s = unicodedata.normalize("NFKD", s)
    return s

def norm_categoria(s: str | None) -> str | None:
    if s is None or str(s).strip() == "":
        return None
    base = normalize_text(s).casefold()
    mapping = {
        "electronica": "Electrónica",
        "electrónica": "Electrónica",
        "electro": "Electrónica",
        "hogar": "Hogar",
        "ferreteria": "Ferretería",
        "ferretería": "Ferretería",
    }
    return mapping.get(base, s.strip().title())

def read_csv_any(path: str) -> pl.DataFrame:
    # 1er intento UTF-8 tolerante a filas “ragged”
    try:
        return pl.read_csv(
            path,
            try_parse_dates=True,
            truncate_ragged_lines=True
        )
    except Exception:
        # 2do intento Latin-1, también tolerante
        return pl.read_csv(
            path,
            try_parse_dates=True,
            encoding="latin1",
            truncate_ragged_lines=True
        )

def read_excel_any(path: str) -> pl.DataFrame:
    # Intento directo (puede devolver DF o dict)
    res: Any = pl.read_excel(path, raise_if_empty=False)
    if isinstance(res, dict):
        # Prioriza hoja cuyo nombre contenga "inventario"
        for name, df in res.items():
            if "inventario" in str(name).casefold() and df is not None and df.width > 0 and df.height > 0:
                return df
        # Si no, toma la primera NO vacía
        for df in res.values():
            if df is not None and df.width > 0 and df.height > 0:
                return df
        # Ninguna con datos → DF vacío
        return pl.DataFrame()
    # Ya es DF
    return res if res is not None else pl.DataFrame()

def unify_columns(df: pl.DataFrame, src_name: str) -> Optional[pl.DataFrame]:
    """
    Mapea columnas heterogéneas hacia el esquema estándar.
    Si no reconoce al menos una columna útil, devuelve None para saltar el archivo.
    """
    std_order = ["Codigo_Producto","Nombre","Descripcion_Producto","Stock","Categoria","Imagen"]

    candidates = {
        "Codigo_Producto": [
            "codigo producto","codigo_producto","codigo","sku",
            "código producto","código","codigo_producto_sku","codigo producto sku"
        ],
        "Nombre": ["nombre","nombre_producto","producto","producto nombre"],
        "Descripcion_Producto": [
            "descripción del producto","descripcion del producto","descripcion",
            "descripcion_producto","desc.","detalle"
        ],
        "Stock": ["stock","existencias","cantidad","inventario","qty"],
        "Categoria": ["categoria","categoría","linea","línea","familia"],
        "Imagen": [
            "imagen","url_imagen","ruta","foto","image","picture",
            "imagen(url del servidor)","imagen url del servidor"
        ],
    }

    cols_lc = {c.lower().strip(): c for c in df.columns}

    def find_match(name_list: list[str]) -> Optional[str]:
        # igualdad estricta sin espacios
        for want in name_list:
            want_n = want.replace(" ", "")
            for lc, orig in cols_lc.items():
                if want_n == lc.replace(" ", ""):
                    return orig
        # fallback: contiene token
        for want in name_list:
            token = want.split()[0]
            for lc, orig in cols_lc.items():
                if token in lc:
                    return orig
        return None

    selected_cols: dict[str, pl.Series] = {}
    for std in std_order:
        col = find_match(candidates[std])
        if col:
            selected_cols[std] = df.get_column(col)

    # nada útil reconocido → None
    if not selected_cols:
        return None

    out = pl.DataFrame(selected_cols)

    # completar faltantes como None
    for std in std_order:
        if std not in out.columns:
            out = out.with_columns(pl.lit(None).alias(std))

    # forzar tipos mínimos
    out = (
        out
        .with_columns([
            pl.col("Codigo_Producto").cast(pl.Utf8, strict=False),
            pl.col("Nombre").cast(pl.Utf8, strict=False),
            pl.col("Descripcion_Producto").cast(pl.Utf8, strict=False),
            pl.col("Stock").cast(pl.Int64, strict=False),
            pl.col("Categoria").cast(pl.Utf8, strict=False),
            pl.col("Imagen").cast(pl.Utf8, strict=False),
        ])
        .select(std_order)
    )
    return out

def clean_transform(df: pl.DataFrame) -> tuple[pl.DataFrame, dict]:
    """
    Limpia y normaliza. Devuelve (DataFrame_limpio, reporte_descartes)
    reporte_descartes: {"nombre_vacio": n, "stock_invalido": m, "duplicados_codigo": k}
    """
    total_in = df.height

    # Normalización básica
    norm = (
        df
        .with_columns([
            pl.col("Codigo_Producto").cast(pl.Utf8).str.strip_chars().alias("Codigo_Producto"),
            pl.col("Nombre").cast(pl.Utf8).str.strip_chars().alias("Nombre"),
            pl.col("Descripcion_Producto").cast(pl.Utf8).str.strip_chars().alias("Descripcion_Producto"),
            pl.col("Categoria").cast(pl.Utf8).str.strip_chars().alias("Categoria"),
            pl.col("Imagen").cast(pl.Utf8).str.strip_chars().alias("Imagen"),
            pl.col("Stock").cast(pl.Int64, strict=False).alias("Stock"),
        ])
    )

    # Reglas de descarte
    mask_nombre_vacio = (pl.col("Nombre").is_null() | (pl.col("Nombre").str.strip_chars() == ""))
    mask_stock_inval  = (pl.col("Stock").is_null() | (pl.col("Stock") < 0))

    # Conteos antes de filtrar
    nombre_vacio_cnt = norm.filter(mask_nombre_vacio).height
    stock_inval_cnt  = norm.filter(~mask_nombre_vacio & mask_stock_inval).height

    # Aplicar filtros
    filtered = norm.filter(~mask_nombre_vacio & ~mask_stock_inval)

    # Deduplicación por PK (mantén el último visto)
    before_dedup = filtered.height
    deduped = filtered.unique(keep="last", subset=["Codigo_Producto"])
    duplicados_cnt = before_dedup - deduped.height

    reporte = {
        "total_entrada": total_in,
        "nombre_vacio": nombre_vacio_cnt,
        "stock_invalido": stock_inval_cnt,
        "duplicados_codigo": duplicados_cnt,
        "total_salida": deduped.height,
    }
    return deduped, reporte

def load_to_mysql(df: pl.DataFrame):
    host = os.getenv("DB_HOST", "127.0.0.1")
    port = int(os.getenv("DB_PORT", "3306"))
    user = os.getenv("DB_USER")
    pwd  = os.getenv("DB_PASSWORD")
    db   = os.getenv("DB_NAME", "dw")

    url = URL.create(
        drivername="mysql+pymysql",
        username=user,
        password=pwd,
        host=host,
        port=port,
        database=db,
    )

    connect_args = {}
    if os.getenv("MYSQL_SSL_CA"):
        connect_args["ssl"] = {
            "ca": os.getenv("MYSQL_SSL_CA"),
            "cert": os.getenv("MYSQL_SSL_CERT"),
            "key": os.getenv("MYSQL_SSL_KEY"),
        }

    # Retry con backoff
    last_err = None
    for attempt in range(1, 6):  # 5 intentos
        try:
            engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
            with engine.begin() as conn:
                # --- (tu lógica actual de inserción) ---
                rows = df.with_columns(pl.lit(datetime.now(timezone.utc)).alias("Fecha_Carga_DW"))
                cols = ["Codigo_Producto","Nombre","Descripcion_Producto","Stock","Categoria","Imagen","Fecha_Carga_DW"]
                values = list(rows.select(cols).iter_rows())
                if values:
                    placeholders = ", ".join(["%s"] * len(cols))
                    updates = ", ".join([f"{c}=VALUES({c})" for c in cols if c != "Codigo_Producto"])
                    sql = f"INSERT INTO dw_inventario ({', '.join(cols)}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {updates};"
                    conn.connection.cursor().executemany(sql, values)
            last_err = None
            break
        except Exception as e:
            last_err = e
            # 1 intento con host alterno “localhost” si estabas con 127.0.0.1
            if attempt == 2 and host == "127.0.0.1":
                host = "localhost"
                url = URL.create(
                    drivername="mysql+pymysql", username=user, password=pwd,
                    host=host, port=port, database=db
                )
            time.sleep(min(1 * attempt, 5))  # backoff 1s→5s

    if last_err is not None:
        # Propaga el error para que lo capture main() y quede logueado
        raise last_err

def discover_sources(base_folder: Path, patterns: List[str]) -> List[Path]:
    seen: Set[str] = set()
    out: List[Path] = []
    base = str(base_folder.resolve()).lower()
    for pat in patterns:
        for p in base_folder.rglob(pat):
            if not p.is_file():
                continue
            ap = str(p.resolve())
            ap_l = ap.lower()
            # Ignorar carpetas de entorno
            if "\\.venv\\" in ap_l or "/.venv/" in ap_l or "site-packages" in ap_l:
                continue
            # (opcional) ignora /tests/ por si acaso
            if "\\tests\\" in ap_l or "/tests/" in ap_l:
                continue
            if ap not in seen:
                seen.add(ap)
                out.append(p)
    return out

def main() -> int:
    base_dir = Path(__file__).parent

    # 1) Cargar .env local y sobreescribir cualquier DB_* heredada del entorno
    load_dotenv(dotenv_path=base_dir / ".env", override=True)

    logger = init_logger(base_dir)

    corr = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()

    logger.info("ETL start", extra={"event": "start", "correlation_id": corr})
    logger.info("db_config", extra={
        "event": "db_config",
        "correlation_id": corr,
        "data": {
            "host": os.getenv("DB_HOST"),
            "port": os.getenv("DB_PORT"),
            "user": os.getenv("DB_USER"),
            "db":   os.getenv("DB_NAME"),
        },
    })

    # 2) Config con defaults seguros
    cfg = load_config()
    cfg_sources = cfg.get("sources", {})
    base_folder = Path(cfg_sources.get("base_folder", str(base_dir)))
    patterns = cfg_sources.get("discover_patterns", ["*.xlsx", "*.csv"])

    # --- DISCOVERY ---
    sources = discover_sources(base_folder, patterns)
    logger.info(
        "sources_found",
        extra={
            "event": "sources_found",
            "correlation_id": corr,
            "data": {"count": len(sources), "paths": [str(p) for p in sources]},
        },
    )

    if not sources:
        audit = {
            "correlation_id": corr,
            "rows_extracted": 0,
            "rows_transformed": 0,
            "rows_loaded": 0,
            "errors": [f"No se encontraron .xlsx/.csv en {str(base_folder)}"],
            "started_at_utc": started_at,
            "ended_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        _persist_audit(base_dir, audit)
        logger.info("end", extra={"event": "end", "correlation_id": corr, "data": audit})
        return 0

    frames: list[pl.DataFrame] = []
    errors: list[str] = []
    rows_extracted = 0

    for p in sources:
        try:
            if p.suffix.lower() in (".xlsx", ".xls"):
                df = read_excel_any(str(p))
            else:
                df = read_csv_any(str(p))
            logger.info(
                "source_headers",
                extra={
                    "event": "source_headers",
                    "correlation_id": corr,
                    "data": {"file": p.name, "columns": df.columns},
                },
            )
            rows_extracted += df.height
            uni = unify_columns(df, p.name)
            if uni is None:
                msg = f"{p.name}: Encabezados no reconocidos -> {df.columns}"
                errors.append(msg)
                logger.warning(msg, extra={"event": "transform_skip", "correlation_id": corr})
                continue
            frames.append(uni)
        except Exception as e:
            msg = f"{p.name}: {e}"
            errors.append(msg)
            logger.exception(msg, extra={"event": "extract_error", "correlation_id": corr})

    raw = pl.concat(frames, how="vertical_relaxed") if frames else pl.DataFrame()
    if raw.is_empty() or len(raw.columns) == 0:
        audit = {
            "correlation_id": corr,
            "rows_extracted": rows_extracted,
            "rows_transformed": 0,
            "rows_loaded": 0,
            "errors": errors + ["No hay datos válidos tras unificación; revise encabezados."],
            "started_at_utc": started_at,
            "ended_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        _persist_audit(base_dir, audit)
        logger.info("end", extra={"event": "end", "correlation_id": corr, "data": audit})
        return 0

    # --- TRANSFORM ---
    tr, rep = clean_transform(raw)
    if tr.is_empty():
        audit = {
            "correlation_id": corr,
            "rows_extracted": rows_extracted,
            "rows_transformed": 0,
            "rows_loaded": 0,
            "errors": errors + ["Sin filas válidas tras limpieza."],
            "transform_discards": rep,
            "started_at_utc": started_at,
            "ended_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        _persist_audit(base_dir, audit)
        logger.info("end", extra={"event": "end", "correlation_id": corr, "data": audit})
        return 0

    # --- PARQUET (control)
    parquet_out = cfg.get("load", {}).get(
        "parquet_out", str(base_dir / "data_curated" / "inventario_curado.parquet")
    )
    Path(parquet_out).parent.mkdir(parents=True, exist_ok=True)
    tr.write_parquet(parquet_out, compression="zstd", statistics=True)

    # --- LOAD ---
    rows_loaded = 0
    try:
        load_to_mysql(tr)
        rows_loaded = tr.height
    except Exception as e:
        msg = f"load_error: {e}"
        errors.append(msg)
        logger.exception(msg, extra={"event": "load_error", "correlation_id": corr})

    audit = {
        "correlation_id": corr,
        "rows_extracted": rows_extracted,
        "rows_transformed": tr.height,
        "rows_loaded": rows_loaded,
        "errors": errors,
        "transform_discards": rep,
        "started_at_utc": started_at,
        "ended_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _persist_audit(base_dir, audit)
    logger.info("end", extra={"event": "end", "correlation_id": corr, "data": audit})
    return 0


if __name__ == "__main__":
    sys.exit(main())
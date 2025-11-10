# Proyecto: ETL Seguro de Inventarios

Ruta de trabajo sugerida (Windows): `C:\Data\ProyectoICiberseguridad`

## Estructura
- `etl_inventario.py`: Script principal (descubre .xlsx/.csv en la carpeta base).
- `configs\config.yaml`: Configuración general.
- `sql\init_dw.sql`: Script para crear DB, tabla y usuario mínimo.
- `scripts\create_venv.ps1`: Crea entorno virtual.
- `scripts\run.ps1` / `scripts\run.bat`: Ejecutan el ETL.
- `requirements.txt`
- `.env.example` (copiar a `.env` y completar credenciales)
- `data_curated\` (salidas Parquet)

## Pasos
1. Copia todo este proyecto a `C:\Data\ProyectoICiberseguridad`.
2. Duplica `.env.example` como `.env` y ajusta credenciales.
3. Ejecuta `scripts\create_venv.ps1` (PowerShell) para crear el entorno.
4. En MySQL, corre `sql\init_dw.sql` (ajusta el password del usuario).
5. Coloca tus archivos `*.xlsx` y `*.csv` en `C:\Data\ProyectoICiberseguridad`.
6. Ejecuta `scripts\run.ps1` o `scripts\run.bat`.

## Seguridad
- No commitees `.env`. Usa usuario con mínimos privilegios.
- Habilita TLS en producción (variables `MYSQL_SSL_*`).


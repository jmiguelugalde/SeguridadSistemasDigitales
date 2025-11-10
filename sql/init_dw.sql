CREATE DATABASE IF NOT EXISTS dw CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE dw;

CREATE TABLE IF NOT EXISTS dw_inventario (
  Codigo_Producto       VARCHAR(64)   NOT NULL,
  Nombre                VARCHAR(255)  NOT NULL,
  Descripcion_Producto  TEXT          NULL,
  Stock                 INT           NOT NULL CHECK (Stock >= 0),
  Categoria             VARCHAR(128)  NULL,
  Imagen                VARCHAR(512)  NULL,
  Fecha_Carga_DW        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (Codigo_Producto),
  KEY idx_categoria (Categoria),
  KEY idx_nombre (Nombre)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Usuario mínimo (ajusta host y password)
-- Nota: si usas MariaDB/MySQL con auth nativa, adapta 'IDENTIFIED BY' según versión
CREATE USER IF NOT EXISTS 'etl_user'@'localhost' IDENTIFIED BY 'admin123';
GRANT SELECT, INSERT, UPDATE ON dw.* TO 'etl_user'@'localhost';
FLUSH PRIVILEGES;

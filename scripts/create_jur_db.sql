DO
$$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'jur_user') THEN
        CREATE ROLE jur_user LOGIN PASSWORD 'jur_password';
    END IF;
END
$$;

SELECT 'CREATE DATABASE jur_db OWNER jur_user'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'jur_db')\gexec

GRANT ALL PRIVILEGES ON DATABASE jur_db TO jur_user;

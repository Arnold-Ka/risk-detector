DROP DATABASE risks IF EXISTS;

CREATE DATABASE risks;

USE risks;

CREATE TABLE users(
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firstname VARCHAR(255),
    lastname VARCHAR(255),
    email VARCHAR UNIQUE(255),
    phone_number VARCHAR(25),
)
CREATE EXTENSION pg_uuidv7;


CREATE TABLE companies(
    id UUID PRIMARY KEY DEFAULT gen_ramdom_uuid(),
    company_name VARCHAR(255),
    
)



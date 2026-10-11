CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE companies (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cik integer UNIQUE NOT NULL,
    name text NOT NULL,
    ticker text,
    sector_group text NOT NULL DEFAULT 'other', -- 'bank' | 'insurance' | 'reit' | 'other'
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE filings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id uuid NOT NULL REFERENCES companies(id),
    accession text UNIQUE NOT NULL,
    form_type text NOT NULL,
    filed_at date NOT NULL,
    url text NOT NULL
);

CREATE TABLE facts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id uuid NOT NULL REFERENCES companies(id),
    filing_id uuid REFERENCES filings(id),
    concept text NOT NULL,
    value numeric NOT NULL,
    period_end date NOT NULL,
    fiscal_year integer,
    fiscal_quarter integer
);

CREATE TABLE signals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id uuid NOT NULL REFERENCES companies(id),
    signal_type text NOT NULL,
    value numeric,
    severity text NOT NULL,
    computed_at date NOT NULL,
    filing_id uuid REFERENCES filings(id)
);

CREATE TABLE prices (
    company_id uuid NOT NULL  REFERENCES companies(id),
    date date NOT NULL,
    close numeric NOT NULL,
    PRIMARY KEY (company_id, date)
);

CREATE TABLE users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text UNIQUE NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE watchlists(
    user_id uuid NOT NULL REFERENCES users(id),
    company_id uuid NOT NUll REFERENCES companies(id),
    added_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, company_id)
);
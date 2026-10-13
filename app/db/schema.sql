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
    fiscal_quarter integer,
    -- Un seul fait par (entreprise, concept, date de fin) : c'est la clé
    -- d'idempotence de l'ingestion (phase 1) — rejouer le chargeur met à
    -- jour la valeur au lieu de dupliquer (restatement le plus récent
    -- gagne, même règle que dans app/normalize/loader.py).
    CONSTRAINT facts_company_concept_period_unique UNIQUE (company_id, concept, period_end)
);

CREATE TABLE signals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id uuid NOT NULL REFERENCES companies(id),
    -- 'altman' | 'piotroski' | 'beneish' | 'divergence' | 'runway' | 'composite'
    signal_type text NOT NULL,
    -- Exercice auquel le score se rapporte (date de fin de période du
    -- bilan) — PAS la date de calcul : l'historique par exercice est ce
    -- qui alimente le backtest et les graphiques d'évolution (§4 « garder
    -- l'historique »). computed_at = date d'exécution du job nocturne.
    period_end date NOT NULL,
    value numeric,
    -- 'saine' | 'vigilance' | 'défaillance' pour les composants ;
    -- 'faible' | 'modéré' | 'élevé' | 'critique' pour le composite.
    severity text NOT NULL,
    -- Détail du calcul (ratios intermédiaires, critères F1-F9, sources) :
    -- c'est ce champ qui rend chaque score explicable et auditable.
    details jsonb,
    computed_at date NOT NULL,
    filing_id uuid REFERENCES filings(id),
    -- Un seul résultat par (entreprise, type, exercice) : le job nocturne
    -- remplace les lignes d'un exercice au lieu de les dupliquer à chaque
    -- exécution (clé d'idempotence, même esprit que facts).
    CONSTRAINT signals_company_type_period_unique UNIQUE (company_id, signal_type, period_end)
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
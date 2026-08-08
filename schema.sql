CREATE TABLE IF NOT EXISTS crawler_data (
    id               bigserial PRIMARY KEY,
    url              character varying(2048),
    url_hash         character varying(64),
    content_type     character varying(255),
    data             text,
    crawl_timestamp  timestamp with time zone,
    last_updated     timestamp with time zone,
    last_accessed    timestamp with time zone,
    created_at       timestamp with time zone
);
-- Notices (NTC): one message to each human seat when a wake opens.
-- The address is the account's, set from the game menu; empty or NULL sends nothing.
-- zone is an IANA name: the close time in a notice is given in it.
CREATE TABLE web_notice_addresses (
    account_id TEXT        PRIMARY KEY REFERENCES web_accounts ON DELETE CASCADE,
    address    TEXT,
    zone       TEXT        NOT NULL DEFAULT 'America/New_York',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per seat and wake once its notice has gone, so a wake opened again by a
-- resumed run sends nothing twice. A send that fails deletes its row.
CREATE TABLE web_notices_sent (
    campaign_id TEXT        NOT NULL,
    seat_id     TEXT        NOT NULL,
    wake        INTEGER     NOT NULL,
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (campaign_id, seat_id, wake)
);

GRANT SELECT, INSERT, UPDATE ON web_notice_addresses TO {app_role};
GRANT SELECT, INSERT, DELETE ON web_notices_sent TO {app_role};

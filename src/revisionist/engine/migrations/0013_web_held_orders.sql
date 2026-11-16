-- Held orders (HLD): an order a seat gives after it has committed, or while its wake
-- is closing, waits here and is filed when the next wake opens, in held_id order.
-- wake is the wake it was given in; filed_in the wake it was filed or dropped at
-- (NULL while it waits); dropped says why one did not go through.
CREATE TABLE web_held_orders (
    held_id     BIGSERIAL   PRIMARY KEY,
    campaign_id TEXT        NOT NULL,
    seat_id     TEXT        NOT NULL,
    wake        INTEGER     NOT NULL,
    action      TEXT        NOT NULL,
    args        JSONB       NOT NULL,
    label       TEXT        NOT NULL,
    held_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    filed_in    INTEGER,
    dropped     TEXT
);

CREATE INDEX web_held_orders_waiting ON web_held_orders (campaign_id, held_id)
    WHERE filed_in IS NULL;

GRANT SELECT, INSERT, UPDATE, DELETE ON web_held_orders TO {app_role};
-- INSERT into a BIGSERIAL column needs the sequence too.
GRANT USAGE ON SEQUENCE web_held_orders_held_id_seq TO {app_role};

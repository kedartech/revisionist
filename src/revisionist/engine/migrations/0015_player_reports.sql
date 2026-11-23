-- Player reports (RPS): a bug, an idea or something confusing, filed from the room.
-- Pinned to the moment: seq is the log position and state_hash the state's hash when it
-- was filed; wake the realism wake then open (NULL before the first). words are sealed to
-- the seat in a sealed campaign. status is new, seen or acted; reply is the host's or
-- the operator's one line back. Rows in discord_bugs stay where they are.
CREATE TABLE player_reports (
    report_id   BIGSERIAL   PRIMARY KEY,
    campaign_id TEXT        NOT NULL,
    seat_id     TEXT        NOT NULL,
    account_id  TEXT        NOT NULL,
    kind        TEXT        NOT NULL CHECK (kind IN ('bug', 'idea', 'confusing')),
    wake        INTEGER,
    seq         INTEGER     NOT NULL,
    state_hash  TEXT        NOT NULL,
    words       TEXT        NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'seen', 'acted')),
    reply       TEXT        NOT NULL DEFAULT '',
    filed_at    TIMESTAMPTZ NOT NULL,
    marked_at   TIMESTAMPTZ
);

CREATE INDEX player_reports_game ON player_reports (campaign_id, report_id);
CREATE INDEX player_reports_account ON player_reports (account_id, filed_at);
CREATE INDEX player_reports_filed ON player_reports (filed_at);

-- One row per day whose digest has gone, so a day is never counted out twice.
CREATE TABLE player_report_digests (
    day     DATE        PRIMARY KEY,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE ON player_reports TO {app_role};
-- INSERT into a BIGSERIAL column needs the sequence too.
GRANT USAGE ON SEQUENCE player_reports_report_id_seq TO {app_role};
GRANT SELECT, INSERT, DELETE ON player_report_digests TO {app_role};

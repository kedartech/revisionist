-- Limits on what costs money (LIM): one row for each counted try, so the hourly lines on
-- model calls and the sign-up, sign-in and recovery limits hold across a restart. kind
-- names the line (a kind of model call, address-<what>, or signin-failed); key is what it
-- is counted against (an account id, a hash of an address, or a handle). Rows older than
-- their window are deleted as the next try for the same kind and key is counted.
CREATE TABLE web_limit_hits (
    kind TEXT        NOT NULL,
    key  TEXT        NOT NULL,
    at   TIMESTAMPTZ NOT NULL
);

CREATE INDEX web_limit_hits_window ON web_limit_hits (kind, key, at);

GRANT SELECT, INSERT, DELETE ON web_limit_hits TO {app_role};

-- A game that ends keeps its web seats, so each player can open its reveal. A seat
-- with finished_at set is no longer held: the account is free to start or join another.
ALTER TABLE web_seats ADD COLUMN finished_at TIMESTAMPTZ;

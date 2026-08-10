CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- room
CREATE TABLE game_room (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    code VARCHAR(6) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL check (status in ('waiting', 'placement', 'in_progress', 'finished')) DEFAULT 'waiting',
    grid_size INTEGER NOT NULL DEFAULT 15,
    current_turn_id UUID NULL,
        -- FK to game_player.id --> set once both players join; NULL initially
    winner_id UUID NULL,
        -- FK to game_player.id --> set on game over; NULL until then
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE game_room
ADD CONSTRAINT fk_room_current_turn
  FOREIGN KEY (current_turn_id) REFERENCES game_player(id)
  ON DELETE SET NULL;

ALTER TABLE game_room
ADD CONSTRAINT fk_room_winner
  FOREIGN KEY (winner_id) REFERENCES game_player(id)
  ON DELETE SET NULL;

CREATE INDEX idx_game_room_code ON game_room (code);


-- player
CREATE TABLE game_player (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    room_id UUID NOT NULL REFERENCES game_room(id) ON DELETE CASCADE,
    session_key VARCHAR(40) NOT NULL,
        -- Django session key --> identifies the browser/device
    name VARCHAR(30) NOT NULL DEFAULT 'Player',
    ships_placed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (room_id, session_key)
);

CREATE INDEX idx_game_player_room ON game_player (room_id);


-- ship
CREATE TABLE game_ship (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    player_id UUID NOT NULL REFERENCES game_player(id) ON DELETE CASCADE,
    size INTEGER NOT NULL,
    cells JSONB NOT NULL,
        -- ordered list of [row, col] pairs, e.g. [[2,3],[2,4],[2,5]]
    orientation VARCHAR(1) NOT NULL DEFAULT 'H',
        -- 'H' (horizontal) or 'V' (vertical)
    hit_cells JSONB NOT NULL DEFAULT '[]'::JSONB,
        -- list of [row, col] pairs that have been hit
    is_sunk BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX idx_game_ship_player ON game_ship (player_id);


-- game action
CREATE TABLE game_action (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    room_id UUID NOT NULL REFERENCES game_room(id) ON DELETE CASCADE,
    player_id UUID NOT NULL REFERENCES game_player(id) ON DELETE CASCADE,
    action_type VARCHAR(5) NOT NULL check (action_type in ('sonar', 'fire')),
    target_row INTEGER NOT NULL,
    target_col INTEGER NOT NULL,
    result JSONB NULL,
        -- For fire: {"hit": true/false, "ship_name": "...", "sunk": true/false}
        -- For sonar: {"distance": 3.5, "contact": true}
        -- NULL until processed
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_game_action_room ON game_action (room_id);
CREATE INDEX idx_game_action_player ON game_action (player_id);
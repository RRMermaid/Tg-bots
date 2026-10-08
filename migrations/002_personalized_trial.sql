-- Personalised onboarding, goal-aware progress and flexible access grants.
-- All changes are additive; existing diary, weight and notification rows stay intact.
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_username TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_first_name TEXT;

-- Existing rows are legacy users. Rows inserted after this migration default to false.
ALTER TABLE users ADD COLUMN IF NOT EXISTS legacy_user BOOLEAN;
UPDATE users SET legacy_user = TRUE WHERE legacy_user IS NULL;
ALTER TABLE users ALTER COLUMN legacy_user SET DEFAULT FALSE;
ALTER TABLE users ALTER COLUMN legacy_user SET NOT NULL;

ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarding_version INT NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS target_weight DOUBLE PRECISION;
ALTER TABLE users ADD COLUMN IF NOT EXISTS limitations TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS focus_areas JSONB NOT NULL DEFAULT '[]';
ALTER TABLE users ADD COLUMN IF NOT EXISTS deficit_percent INT NOT NULL DEFAULT 10;
ALTER TABLE users ADD COLUMN IF NOT EXISTS calorie_lower INT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS calorie_upper INT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS goal_start_weight DOUBLE PRECISION;
ALTER TABLE users ADD COLUMN IF NOT EXISTS milestones_reached INT NOT NULL DEFAULT 0;

ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_started_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS new_user_notified BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE meals ADD COLUMN IF NOT EXISTS reminder_minutes INT NOT NULL DEFAULT 180;
ALTER TABLE meals ADD COLUMN IF NOT EXISTS composition_comment TEXT;

CREATE TABLE IF NOT EXISTS access_grants (
 id BIGSERIAL PRIMARY KEY,
 user_id BIGINT NOT NULL REFERENCES users(id),
 kind TEXT NOT NULL CHECK (kind IN ('subscription','promo','gift','admin')),
 starts_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 ends_at TIMESTAMPTZ,
 code TEXT,
 details JSONB NOT NULL DEFAULT '{}',
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS access_grants_user_dates
 ON access_grants(user_id,starts_at,ends_at);

CREATE TABLE IF NOT EXISTS daily_checkins (
 user_id BIGINT NOT NULL REFERENCES users(id),
 date DATE NOT NULL,
 sleep_hours DOUBLE PRECISION,
 note TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(user_id,date)
);

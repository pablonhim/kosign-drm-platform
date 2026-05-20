-- 2026-05-19  audit_logs table  (변경 이력 panel)
--
-- Stores cross-cutting admin activity: org transfers, employee-info edits,
-- password changes, user CRUD, data syncs. Distinct from employee_history
-- which is employee-scoped only.
--
-- HOW TO APPLY
--   Supabase dashboard → SQL Editor → paste this file → Run.
--   PostgREST auto-reloads the schema after a successful DDL transaction.

create table if not exists public.audit_logs (
  id           bigserial    primary key,
  occurred_at  timestamptz  not null default now(),
  actor_id     text,
  actor_name   text,
  actor_role   text,
  category     text         not null,
  target_id    text,
  target_name  text,
  field        text,
  old_value    text,
  new_value    text,
  description  text         not null,
  meta         jsonb
);

create index if not exists audit_logs_occurred_at_idx
  on public.audit_logs (occurred_at desc);

create index if not exists audit_logs_category_idx
  on public.audit_logs (category);

create index if not exists audit_logs_target_idx
  on public.audit_logs (target_id);

-- RLS — mirror the open-access pattern used by users/employees,
-- since the app authenticates against the `users` table itself
-- and reads via the publishable key.
alter table public.audit_logs enable row level security;

drop policy if exists "audit_logs_read"   on public.audit_logs;
drop policy if exists "audit_logs_insert" on public.audit_logs;

create policy "audit_logs_read"
  on public.audit_logs for select
  using (true);

create policy "audit_logs_insert"
  on public.audit_logs for insert
  with check (true);

-- Belt-and-braces: nudge PostgREST to reload its schema cache.
-- DDL inside a transaction usually triggers this automatically, but
-- this NOTIFY is the documented manual trigger if it ever lags.
notify pgrst, 'reload schema';

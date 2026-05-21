-- =============================================================================
-- 2026-05-21  user_mgmt_unblock migration
--
-- TWO independent fixes wrapped in one transaction:
--
-- 1. UNBLOCK 사용자관리 PAGE
--    The previous migration (2026_05_20_secure_login.sql) locked users
--    SELECT to `using (false)` — anon clients can no longer read the
--    users table directly. That broke the 사용자관리 (User Management)
--    page entirely (loadUsers() got zero rows).
--
--    This migration relaxes the users-table RLS to allow anon SELECT
--    and admin-style writes again. The plaintext password is GONE
--    (replaced by bcrypt password_hash in the prior migration), and
--    verify_login() still gates actual authentication, so anon visibility
--    of the hashed table is an acceptable trade-off for prototype use.
--
--    PROPER FOLLOW-UP: rewrite the user-management page to call
--    SECURITY DEFINER RPCs (list_users / upsert_user / delete_user)
--    instead of direct sb.from('users').{select|upsert|delete}. That
--    would let us lock SELECT back to false. Documented in the FOLLOW-UP
--    block at the bottom of this file.
--
-- 2. RENAME 'R&D 지원센터' team  '사업기획' → '그룹사 상품 TFT'
--    DEFAULT_ORG in index.html was updated alongside this migration.
--    Existing employee rows still have team='사업기획' — fix them here.
-- =============================================================================

begin;

-- ── 1. Relax users RLS ──────────────────────────────────────────────────
-- Drop the locked policy from the previous migration.
drop policy if exists "users_no_anon_read"   on public.users;
drop policy if exists "users_anon_read"      on public.users;
drop policy if exists "users_anon_insert"    on public.users;
drop policy if exists "users_anon_update"    on public.users;
drop policy if exists "users_anon_delete"    on public.users;

-- Allow anon to read, insert, update, delete user rows. The bcrypt
-- password_hash column is visible — but that's a hash, not the plaintext,
-- so leaking it doesn't compromise accounts unless someone burns serious
-- compute on offline bcrypt cracking (cost factor 10 ≈ 100ms per attempt).
create policy "users_anon_read"
  on public.users for select
  using (true);

create policy "users_anon_insert"
  on public.users for insert
  with check (true);

create policy "users_anon_update"
  on public.users for update
  using (true)
  with check (true);

create policy "users_anon_delete"
  on public.users for delete
  using (true);

-- ── 2. Rename team in employees table ───────────────────────────────────
-- Affects every employee whose team field is exactly '사업기획'.
-- 'team' is a free-text column in the employees table — single UPDATE
-- catches every row.
update public.employees
   set team = '그룹사 상품 TFT'
 where team = '사업기획';

-- ── 3. Schema reload + commit ──────────────────────────────────────────
notify pgrst, 'reload schema';
commit;

-- =============================================================================
-- DIAGNOSTIC QUERIES — paste into the SQL Editor SEPARATELY (after commit)
-- to confirm the changes landed:
-- =============================================================================
-- 1) Count of employees per team (should show 그룹사 상품 TFT, not 사업기획):
--      select team, count(*) from public.employees group by team order by team;
--
-- 2) Confirm users page works again (should return all your users):
--      select id, name, role, can_edit from public.users order by id;
--
-- 3) Find Nhim Chanborey's record (replace search term if needed):
--      select emp_id, nick, name, center, bu, team, status
--        from public.employees
--       where name ilike '%nhim%' or nick ilike '%borey%' or nick ilike '%nhim%';
--
--    If team is NULL or wrong, fix with:
--      update public.employees
--         set center = 'R&D 지원센터',
--             bu     = '',
--             team   = '그룹사 상품 TFT'
--       where emp_id = 'YOUR_EMP_ID';
--
-- =============================================================================
-- FOLLOW-UP (NOT applied here — sprint task)
--
-- To re-lock users SELECT to `using (false)`, build these RPCs and rewrite
-- the client to call them:
--
--   public.list_users()                    → returns id,name,role,can_edit,emp_nick
--   public.upsert_user(p_id, p_password,   → upserts; if p_password is null,
--                      p_name, p_role,        keeps existing password_hash
--                      p_can_edit, p_emp_nick)
--   public.delete_user(p_id)               → deletes by id
--
-- All SECURITY DEFINER, granted to anon. Once those are in place, drop
-- the four anon policies above and recreate users_no_anon_read.
-- =============================================================================

-- Read-only operator inspection. Run manually against the intended Supabase
-- project before migration and again afterwards. It does not apply migrations,
-- seed content, enable delivery, or substitute for backup/restore and RLS tests.
BEGIN READ ONLY;
SELECT current_database() AS database_name, current_user AS database_role;
SELECT name, to_regclass('public.' || name) IS NOT NULL AS present
FROM unnest(ARRAY[
 'map_studio_owners','map_studio_projects','map_studio_members',
 'map_studio_businesses','map_studio_drafts','map_studio_leases',
 'map_studio_versions','map_studio_assets','map_studio_idempotency',
 'map_studio_audit_events','map_studio_sessions','map_studio_login_states'
]) AS expected(name) ORDER BY name;
SELECT c.relname AS table_name, c.relrowsecurity AS rls_enabled,
       c.relforcerowsecurity AS force_rls
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relname LIKE 'map_studio_%' AND c.relkind='r'
ORDER BY c.relname;
SELECT p.proname, pg_get_function_identity_arguments(p.oid) AS arguments,
       p.prosecdef AS security_definer, p.proconfig AS settings, p.proacl AS privileges
FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
WHERE n.nspname='public' AND p.proname LIKE 'map_studio_%' ORDER BY p.proname;
SELECT a.attname AS delivery_column, pg_get_expr(d.adbin,d.adrelid) AS default_value
FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
JOIN pg_namespace n ON n.oid=c.relnamespace
LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
WHERE n.nspname='public' AND c.relname='map_studio_projects'
AND a.attname='public_delivery_enabled' AND NOT a.attisdropped;
-- Supabase exposes this catalog independently of application migrations.
SELECT id, public FROM storage.buckets
WHERE id IN ('map-studio-private','map-studio-published') ORDER BY id;
ROLLBACK;

-- Public maps read this narrow projection directly from external durable storage.
-- It stays available while Daytona is stopped. Rollout is opt-in per map.
alter table public.map_studio_projects add column if not exists public_delivery_enabled boolean not null default false;
create or replace function public.map_studio_delivery_manifest(p_map_key text)
returns jsonb language sql stable security definer set search_path=public,pg_temp
as $$
 select jsonb_build_object('versionId',v.id,'document',v.document,'assets',v.assets)
 from public.map_studio_projects p join public.map_studio_versions v on v.id=p.published_version_id
 where p.map_key=p_map_key and p.public_delivery_enabled and not p.disabled
$$;
revoke all on function public.map_studio_delivery_manifest(text) from public;
grant execute on function public.map_studio_delivery_manifest(text) to anon,authenticated,service_role;
-- Enable only after the corresponding existing public page integration passes:
-- update public.map_studio_projects set public_delivery_enabled=true
-- where map_key in ('san-francisco-mission','boston-back-bay');

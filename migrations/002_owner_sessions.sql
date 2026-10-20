-- Server-only auth state. No browser or anonymous role can access these tables/RPCs.
begin;
create table if not exists public.map_studio_sessions (
  token_hash text primary key check(length(token_hash)=64),
  actor_id uuid not null,
  email text not null check(email='splitineu@gmail.com'),
  github_id text not null,
  csrf_token text not null,
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);
create table if not exists public.map_studio_login_states (
  token_hash text primary key check(length(token_hash)=64),
  expires_at timestamptz not null default now()+interval '10 minutes'
);
alter table public.map_studio_sessions enable row level security;
alter table public.map_studio_login_states enable row level security;
revoke all on public.map_studio_sessions, public.map_studio_login_states from public,anon,authenticated;
grant all on public.map_studio_sessions, public.map_studio_login_states to service_role;

create or replace function public.map_studio_login_state_create(p_hash text) returns boolean
language plpgsql security definer set search_path=public,pg_temp as $$
begin
  delete from map_studio_login_states where expires_at < now();
  insert into map_studio_login_states(token_hash) values(p_hash);
  return true;
end $$;
create or replace function public.map_studio_login_state_consume(p_hash text) returns boolean
language plpgsql security definer set search_path=public,pg_temp as $$
declare consumed text;
begin
  delete from map_studio_login_states where token_hash=p_hash and expires_at>now() returning token_hash into consumed;
  return consumed is not null;
end $$;
create or replace function public.map_studio_session_create(
 p_hash text,p_actor uuid,p_email text,p_github_id text,p_csrf text,p_hours integer
) returns boolean language plpgsql security definer set search_path=public,pg_temp as $$
begin
  if p_email<>'splitineu@gmail.com' or p_hours not between 1 and 8 then
    raise exception 'owner_required' using errcode='42501';
  end if;
  delete from map_studio_sessions where expires_at<now();
  insert into map_studio_sessions(token_hash,actor_id,email,github_id,csrf_token,expires_at)
  values(p_hash,p_actor,p_email,p_github_id,p_csrf,now()+make_interval(hours=>p_hours));
  return true;
end $$;
create or replace function public.map_studio_session_get(p_hash text) returns jsonb
language sql security definer set search_path=public,pg_temp as $$
 select jsonb_build_object('id',actor_id,'email',email,'csrfToken',csrf_token,
 'expiresAt',extract(epoch from expires_at)::bigint)
 from map_studio_sessions where token_hash=p_hash and expires_at>now()
$$;
create or replace function public.map_studio_session_delete(p_hash text) returns boolean
language plpgsql security definer set search_path=public,pg_temp as $$
begin delete from map_studio_sessions where token_hash=p_hash; return true; end $$;

revoke all on function public.map_studio_login_state_create(text),
 public.map_studio_login_state_consume(text),
 public.map_studio_session_create(text,uuid,text,text,text,integer),
 public.map_studio_session_get(text),public.map_studio_session_delete(text)
 from public,anon,authenticated;
grant execute on function public.map_studio_login_state_create(text),
 public.map_studio_login_state_consume(text),
 public.map_studio_session_create(text,uuid,text,text,text,integer),
 public.map_studio_session_get(text),public.map_studio_session_delete(text)
 to service_role;
commit;

-- Map Studio durable editor boundary. Browser writes go through authenticated
-- RPCs; no BFF operation uses a service-role fallback for user data.

create table if not exists public.map_studio_owners (
  user_id uuid primary key,
  email text not null unique check (lower(email) = 'splitineu@gmail.com'),
  created_at timestamptz not null default now()
);

create table if not exists public.map_studio_projects (
  map_key text primary key check (map_key ~ '^[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?$'),
  title text not null check (length(title) between 1 and 200),
  city text not null check (length(city) between 1 and 120),
  public_path text not null check (length(public_path) between 1 and 300),
  center jsonb not null check (jsonb_typeof(center) = 'array' and jsonb_array_length(center) = 2),
  source_revision text not null check (length(source_revision) between 1 and 200),
  disabled boolean not null default false,
  published_version_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.map_studio_members (
  map_key text not null references public.map_studio_projects(map_key) on delete cascade,
  user_id uuid not null,
  enabled boolean not null default true,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  primary key (map_key, user_id)
);
create table if not exists public.map_studio_businesses (
  map_key text not null references public.map_studio_projects(map_key) on delete cascade,
  id text not null check (length(id) between 1 and 128), name text not null check (length(name) between 1 and 300),
  category text, location jsonb, logo_url text, source_revision text not null,
  primary key (map_key, id), check (location is null or jsonb_typeof(location) = 'object')
);
create table if not exists public.map_studio_drafts (
  map_key text primary key references public.map_studio_projects(map_key) on delete cascade,
  document jsonb not null, revision bigint not null default 0 check (revision >= 0),
  updated_by uuid, updated_at timestamptz not null default now()
);
create table if not exists public.map_studio_leases (
  map_key text primary key references public.map_studio_projects(map_key) on delete cascade,
  user_id uuid not null,
  client_id text not null check (length(client_id) between 1 and 128), expires_at timestamptz not null,
  updated_at timestamptz not null default now()
);
create table if not exists public.map_studio_versions (
  id uuid primary key default gen_random_uuid(), map_key text not null references public.map_studio_projects(map_key) on delete cascade,
  document jsonb not null, assets jsonb not null default '[]'::jsonb, revision bigint not null check (revision >= 0), created_by uuid not null,
  created_at timestamptz not null default now()
);
alter table public.map_studio_projects drop constraint if exists map_studio_projects_published_version_id_fkey;
alter table public.map_studio_projects add constraint map_studio_projects_published_version_id_fkey
  foreign key (published_version_id) references public.map_studio_versions(id) on delete set null;
create table if not exists public.map_studio_assets (
  id uuid primary key default gen_random_uuid(), map_key text not null references public.map_studio_projects(map_key) on delete cascade,
  created_by uuid not null, name text not null check (length(name) between 1 and 300),
  alt_text text not null check (length(alt_text) between 1 and 1000), rights text not null check (length(rights) between 1 and 2000),
  mime_type text not null check (length(mime_type) between 1 and 100), sha256 text not null check (sha256 ~ '^[a-f0-9]{64}$'),
  original_path text not null, processed_path text, width integer check (width is null or width > 0),
  height integer check (height is null or height > 0), byte_size bigint check (byte_size is null or byte_size >= 0),
  state text not null default 'pending' check (state in ('pending','ready','deleted')), created_at timestamptz not null default now()
);
create table if not exists public.map_studio_idempotency (
  map_key text not null references public.map_studio_projects(map_key) on delete cascade,
  user_id uuid not null,
  operation text not null check (operation in ('publish','rollback')), idempotency_key text not null check (length(idempotency_key) between 1 and 128),
  request_fingerprint text not null default '', response jsonb not null, created_at timestamptz not null default now(), primary key(map_key,user_id,operation,idempotency_key)
);
alter table public.map_studio_idempotency add column if not exists request_fingerprint text not null default '';
create table if not exists public.map_studio_audit_events (
  id uuid primary key default gen_random_uuid(), map_key text not null references public.map_studio_projects(map_key) on delete cascade,
  actor_id uuid not null, action text not null check (action in ('publish','rollback','member_set','asset_register','asset_delete','disable')),
  entity_id text, metadata jsonb not null default '{}'::jsonb, created_at timestamptz not null default now()
);
create index if not exists map_studio_members_user_idx on public.map_studio_members(user_id,enabled);
create index if not exists map_studio_businesses_map_idx on public.map_studio_businesses(map_key,id);
create index if not exists map_studio_versions_map_created_idx on public.map_studio_versions(map_key,created_at desc);
create index if not exists map_studio_assets_map_state_idx on public.map_studio_assets(map_key,state);
create index if not exists map_studio_audit_map_created_idx on public.map_studio_audit_events(map_key,created_at desc);

create or replace function public.map_studio_member(p_map_key text,p_user_id uuid)
returns boolean language sql stable security definer set search_path=public,pg_temp
as $$ select p_user_id is not null and exists(
  select 1 from public.map_studio_members m join public.map_studio_projects p on p.map_key=m.map_key
  join public.map_studio_owners o on o.user_id=m.user_id
  where m.map_key=p_map_key and m.user_id=p_user_id and m.enabled and not p.disabled
) $$;
revoke all on function public.map_studio_member(text,uuid) from public,anon,authenticated;
create or replace function public.map_studio_owner(p_actor uuid)
returns boolean language sql stable security definer set search_path=public,pg_temp
as $$ select p_actor is not null and exists(select 1 from public.map_studio_owners where user_id=p_actor) $$;
revoke all on function public.map_studio_owner(uuid) from public,anon,authenticated;


create or replace function public.map_studio_document_valid(p_document jsonb,p_map_key text)
returns boolean language plpgsql immutable
as $$
declare l jsonb; k text; allowed text[];
begin
  if jsonb_typeof(p_document)<>'object' or (select count(*) from jsonb_object_keys(p_document))<>4
    or p_document->>'schemaVersion'<>'1' or p_document->>'mapKey'<>p_map_key or p_document->>'theme' not in('original','paper','sage')
    or jsonb_typeof(p_document->'layers')<>'array' or jsonb_array_length(p_document->'layers')>500 then return false; end if;
  for l in select value from jsonb_array_elements(p_document->'layers') loop
    if jsonb_typeof(l)<>'object' or not(l ?& array['id','kind','name','visible','opacity','minZoom','maxZoom']) then return false; end if;
    k:=l->>'kind'; allowed:=array['id','kind','name','visible','opacity','minZoom','maxZoom','category'];
    if k='artwork' then allowed:=allowed||array['assetId','position','width','height','rotation'];
    elsif k='annotation' then allowed:=allowed||array['text','position']; elsif k='geometry' then allowed:=allowed||array['geometry'];
    elsif k='business' then allowed:=allowed||array['businessId','assetId','highlight']; else return false; end if;
    if exists(select 1 from jsonb_object_keys(l) q where not(q=any(allowed)) or jsonb_typeof(l->'visible')<>'boolean'
      or jsonb_typeof(l->'opacity')<>'number' or (l->>'opacity')::numeric not between 0 and 1
      or jsonb_typeof(l->'minZoom')<>'number' or jsonb_typeof(l->'maxZoom')<>'number'
      or (l->>'minZoom')::numeric not between 0 and 24 or (l->>'maxZoom')::numeric not between 0 and 24
      or (l->>'minZoom')::numeric>(l->>'maxZoom')::numeric) then return false; end if;
    if k='artwork' and not(l ?& array['assetId','position','width','height']) then return false; end if;
    if k='annotation' and not(l ?& array['text','position']) then return false; end if;
    if k='geometry' and not(l ? 'geometry') then return false; end if;
    if k='business' and not(l ? 'businessId') then return false; end if;
  end loop; return true;
exception when others then return false; end $$;
revoke all on function public.map_studio_document_valid(jsonb,text) from public,anon,authenticated;

create or replace function public.map_studio_register_project(p_project jsonb,p_businesses jsonb,p_document jsonb default null,p_owner_id uuid default null,p_owner_email text default 'splitineu@gmail.com')
returns jsonb language plpgsql security definer set search_path=public,pg_temp
as $$
declare key text:=p_project->>'mapKey'; rev text:=p_project->>'sourceRevision'; b jsonb; owner_id uuid:=coalesce(p_owner_id,nullif(p_project->>'ownerId','')::uuid); owner_email text:=coalesce(p_owner_email,p_project->>'ownerEmail','splitineu@gmail.com');
  doc jsonb:=coalesce(p_document,jsonb_build_object('schemaVersion',1,'mapKey',key,'theme','original','layers','[]'::jsonb));
begin
  if jsonb_typeof(p_project)<>'object' or key is null or rev is null or p_project->>'title' is null or p_project->>'city' is null or p_project->>'publicPath' is null then raise exception 'project_contract_invalid' using errcode='22023'; end if;
  if not public.map_studio_document_valid(doc,key) then raise exception 'document_contract_invalid' using errcode='22023'; end if;
  if owner_id is null or lower(owner_email) <> 'splitineu@gmail.com' then raise exception 'owner_required' using errcode='42501'; end if;
  insert into public.map_studio_owners(user_id,email) values(owner_id,owner_email) on conflict(user_id) do update set email=excluded.email;
  insert into public.map_studio_projects(map_key,title,city,public_path,center,source_revision)
  values(key,p_project->>'title',p_project->>'city',p_project->>'publicPath',p_project->'center',rev)
  on conflict(map_key) do update set title=excluded.title,city=excluded.city,public_path=excluded.public_path,center=excluded.center,source_revision=excluded.source_revision,disabled=false,updated_at=now();
  insert into public.map_studio_drafts(map_key,document,revision) values(key,doc,0) on conflict(map_key) do nothing;
  insert into public.map_studio_members(map_key,user_id,enabled) values(key,owner_id,true) on conflict(map_key,user_id) do update set enabled=true,updated_at=now();
  delete from public.map_studio_businesses where map_key=key;
  if jsonb_typeof(p_businesses)='array' then for b in select value from jsonb_array_elements(p_businesses) loop
    insert into public.map_studio_businesses(map_key,id,name,category,location,logo_url,source_revision)
    values(key,b->>'id',b->>'name',b->>'category',nullif(b->'location','null'::jsonb),b->>'logoUrl',rev);
  end loop; end if;
  return jsonb_build_object('mapKey',key);
end $$;
revoke all on function public.map_studio_register_project(jsonb,jsonb,jsonb,uuid,text) from public,anon,authenticated;

create or replace function public.map_studio_list_projects(p_actor uuid)
returns setof public.map_studio_projects language sql stable security definer set search_path=public,pg_temp
as $$ select p.* from public.map_studio_projects p where not p.disabled and public.map_studio_member(p.map_key,p_actor) order by p.city,p.title $$;

create or replace function public.map_studio_get_project(p_map_key text,p_actor uuid)
returns jsonb language plpgsql stable security definer set search_path=public,pg_temp
as $$ declare p public.map_studio_projects; d public.map_studio_drafts;
begin
  if p_actor is null or not public.map_studio_member(p_map_key,p_actor) then raise exception 'membership_required' using errcode='42501'; end if;
  select * into p from public.map_studio_projects where map_key=p_map_key and not disabled; if not found then raise exception 'project_not_found' using errcode='P0002'; end if;
  select * into d from public.map_studio_drafts where map_key=p_map_key;
  return jsonb_build_object('project',jsonb_build_object('mapKey',p.map_key,'title',p.title,'city',p.city,'publicPath',p.public_path,'center',p.center,'sourceRevision',p.source_revision),
    'businesses',coalesce((select jsonb_agg(jsonb_build_object('id',b.id,'name',b.name,'category',b.category,'location',b.location,'logoUrl',b.logo_url) order by b.name) from public.map_studio_businesses b where b.map_key=p_map_key),'[]'::jsonb),
    'draft',jsonb_build_object('document',d.document,'revision',d.revision),'can_edit',true);
end $$;

-- Compatibility name used by the storage boundary.  It remains user scoped
-- and delegates to the same membership check as the editor read.
create or replace function public.map_studio_project(p_map_key text,p_actor uuid)
returns jsonb language sql stable security definer set search_path=public,pg_temp
as $$ select public.map_studio_get_project(p_map_key,p_actor) $$;

create or replace function public.map_studio_acquire_lease(p_map_key text,p_client_id text,p_actor uuid)
returns jsonb language plpgsql security definer set search_path=public,pg_temp
as $$ declare p public.map_studio_projects; old public.map_studio_leases; expiry timestamptz:=now()+interval '2 minutes';
begin
  select * into p from public.map_studio_projects where map_key=p_map_key and not disabled for update;
  if not found then raise exception 'project_not_found' using errcode='P0002'; end if;
  if p_actor is null or not public.map_studio_member(p_map_key,p_actor) then raise exception 'membership_required' using errcode='42501'; end if;
  select * into old from public.map_studio_leases where map_key=p_map_key for update;
  if found and old.expires_at>now() and (old.user_id is distinct from p_actor or old.client_id is distinct from p_client_id) then raise exception 'lease_conflict' using errcode='40001'; end if;
  insert into public.map_studio_leases(map_key,user_id,client_id,expires_at,updated_at) values(p_map_key,p_actor,p_client_id,expiry,now())
    on conflict(map_key) do update set user_id=excluded.user_id,client_id=excluded.client_id,expires_at=excluded.expires_at,updated_at=now();
  return jsonb_build_object('clientId',p_client_id,'expiresAt',expiry);
end $$;

create or replace function public.map_studio_release_lease(p_map_key text,p_client_id text,p_actor uuid)
returns jsonb language plpgsql security definer set search_path=public,pg_temp
as $$ declare p public.map_studio_projects;
begin
  select * into p from public.map_studio_projects where map_key=p_map_key and not disabled for update;
  if not found then raise exception 'project_not_found' using errcode='P0002'; end if;
  if p_actor is null or not public.map_studio_member(p_map_key,p_actor) then raise exception 'membership_required' using errcode='42501'; end if;
  delete from public.map_studio_leases where map_key=p_map_key and user_id=p_actor and client_id=p_client_id;
  return jsonb_build_object('ok',true);
end $$;

create or replace function public.map_studio_save_draft(p_map_key text,p_document jsonb,p_expected_revision bigint,p_client_id text,p_actor uuid)
returns jsonb language plpgsql security definer set search_path=public,pg_temp
as $$ declare p public.map_studio_projects; d public.map_studio_drafts; l public.map_studio_leases; next_revision bigint;
begin
  select * into p from public.map_studio_projects where map_key=p_map_key and not disabled for update;
  if not found then raise exception 'project_not_found' using errcode='P0002'; end if;
  if p_actor is null or not public.map_studio_member(p_map_key,p_actor) then raise exception 'membership_required' using errcode='42501'; end if;
  if not public.map_studio_document_valid(p_document,p_map_key) then raise exception 'document_contract_invalid' using errcode='22023'; end if;
  select * into l from public.map_studio_leases where map_key=p_map_key for update;
  if not found or l.user_id is distinct from p_actor or l.client_id is distinct from p_client_id or l.expires_at<=now() then raise exception 'lease_required' using errcode='42501'; end if;
  select * into d from public.map_studio_drafts where map_key=p_map_key for update; if not found then raise exception 'project_not_found' using errcode='P0002'; end if;
  if d.revision<>p_expected_revision then raise exception 'revision_conflict' using errcode='40001'; end if;
  next_revision:=d.revision+1; update public.map_studio_drafts set document=p_document,revision=next_revision,updated_by=p_actor,updated_at=now() where map_key=p_map_key;
  return jsonb_build_object('revision',next_revision,'document',p_document);
end $$;

create or replace function public.map_studio_list_versions(p_map_key text,p_actor uuid)
returns jsonb language sql stable security definer set search_path=public,pg_temp
as $$ select jsonb_build_object(
  'versions',coalesce((select jsonb_agg(jsonb_build_object('id',v.id,'created_at',v.created_at,'created_by',v.created_by,'revision',v.revision) order by v.created_at desc)
    from public.map_studio_versions v where v.map_key=p_map_key),'[]'::jsonb),
  'published_version_id',(select p.published_version_id from public.map_studio_projects p where p.map_key=p_map_key)
)
where public.map_studio_member(p_map_key,p_actor) $$;

create or replace function public.map_studio_publish(p_map_key text,p_expected_revision bigint,p_client_id text,p_idempotency_key text,p_assets jsonb,p_actor uuid)
returns jsonb language plpgsql security definer set search_path=public,pg_temp
as $$
declare p public.map_studio_projects; d public.map_studio_drafts; l public.map_studio_leases; old jsonb; old_fingerprint text; vid uuid; result jsonb; request_fingerprint text;
begin
  select * into p from public.map_studio_projects where map_key=p_map_key and not disabled for update; if not found then raise exception 'project_not_found' using errcode='P0002'; end if;
  if p_actor is null or not public.map_studio_member(p_map_key,p_actor) then raise exception 'membership_required' using errcode='42501'; end if;
  request_fingerprint:=md5(concat(p_expected_revision::text,'|',p_client_id,'|',p_assets::text));
  select i.response,i.request_fingerprint into old,old_fingerprint from public.map_studio_idempotency i where i.map_key=p_map_key and i.user_id=p_actor and i.operation='publish' and i.idempotency_key=p_idempotency_key for update;
  if old is not null then
    if old_fingerprint<>request_fingerprint then raise exception 'idempotency_conflict' using errcode='40001'; end if;
    return old;
  end if;
  select * into l from public.map_studio_leases where map_key=p_map_key for update;
  if not found or l.user_id is distinct from p_actor or l.client_id is distinct from p_client_id or l.expires_at<=now() then raise exception 'lease_required' using errcode='42501'; end if;
  select * into d from public.map_studio_drafts where map_key=p_map_key for update;
  if d.revision<>p_expected_revision then raise exception 'revision_conflict' using errcode='40001'; end if;
  if exists(select 1 from jsonb_array_elements(d.document->'layers') x where x->>'assetId' is not null and not exists(select 1 from public.map_studio_assets a where a.map_key=p_map_key and a.id::text=x->>'assetId' and a.state='ready' and a.processed_path is not null)) then raise exception 'asset_not_ready' using errcode='42501'; end if;
  if exists(select 1 from jsonb_array_elements(d.document->'layers') x where x->>'kind'='business' and not exists(select 1 from public.map_studio_businesses b where b.map_key=p_map_key and b.id=x->>'businessId')) then raise exception 'business_not_found' using errcode='42201'; end if;
  if jsonb_typeof(p_assets)<>'array' then raise exception 'asset_not_ready' using errcode='42501'; end if;
  if exists(select 1 from jsonb_array_elements(p_assets) x where not exists(select 1 from public.map_studio_assets a where a.map_key=p_map_key and a.id::text=x->>'id' and a.state='ready' and a.processed_path is not null)) then raise exception 'asset_not_ready' using errcode='42501'; end if;
  if exists(select 1 from jsonb_array_elements(d.document->'layers') x where x->>'assetId' is not null and not exists(select 1 from jsonb_array_elements(p_assets) y where y->>'id'=x->>'assetId')) then raise exception 'asset_not_ready' using errcode='42501'; end if;
  insert into public.map_studio_versions(map_key,document,assets,revision,created_by)
    select p_map_key,d.document,coalesce(jsonb_agg(jsonb_build_object('id',a.id,'name',a.name,'altText',a.alt_text,'rights',a.rights,'publicPath',a.sha256||'.webp','width',a.width,'height',a.height,'state','ready') order by a.created_at),'[]'::jsonb),d.revision,p_actor
    from public.map_studio_assets a where a.map_key=p_map_key and a.state='ready' and a.processed_path is not null and a.id::text in (select x->>'id' from jsonb_array_elements(p_assets) x)
    returning id into vid;
  update public.map_studio_projects set published_version_id=vid,updated_at=now() where map_key=p_map_key;
  result:=jsonb_build_object('version_id',vid); insert into public.map_studio_idempotency(map_key,user_id,operation,idempotency_key,request_fingerprint,response) values(p_map_key,p_actor,'publish',p_idempotency_key,request_fingerprint,result);
  insert into public.map_studio_audit_events(map_key,actor_id,action,entity_id,metadata) values(p_map_key,p_actor,'publish',vid::text,jsonb_build_object('revision',d.revision,'assetCount',jsonb_array_length(p_assets)));
  return result;
end $$;

create or replace function public.map_studio_rollback(p_map_key text,p_version_id uuid,p_client_id text,p_idempotency_key text,p_actor uuid)
returns jsonb language plpgsql security definer set search_path=public,pg_temp
as $$
declare p public.map_studio_projects; d public.map_studio_drafts; l public.map_studio_leases; target public.map_studio_versions; old jsonb; old_fingerprint text; result jsonb; request_fingerprint text;
begin
  select * into p from public.map_studio_projects where map_key=p_map_key and not disabled for update; if not found then raise exception 'project_not_found' using errcode='P0002'; end if;
  if p_actor is null or not public.map_studio_member(p_map_key,p_actor) then raise exception 'membership_required' using errcode='42501'; end if;
  request_fingerprint:=md5(concat(p_version_id::text,'|',p_client_id));
  select i.response,i.request_fingerprint into old,old_fingerprint from public.map_studio_idempotency i where i.map_key=p_map_key and i.user_id=p_actor and i.operation='rollback' and i.idempotency_key=p_idempotency_key for update;
  if old is not null then
    if old_fingerprint<>request_fingerprint then raise exception 'idempotency_conflict' using errcode='40001'; end if;
    return old;
  end if;
  select * into l from public.map_studio_leases where map_key=p_map_key for update;
  if not found or l.user_id is distinct from p_actor or l.client_id is distinct from p_client_id or l.expires_at<=now() then raise exception 'lease_required' using errcode='42501'; end if;
  select * into d from public.map_studio_drafts where map_key=p_map_key for update;
  select * into target from public.map_studio_versions where id=p_version_id and map_key=p_map_key; if not found then raise exception 'version_not_found' using errcode='P0002'; end if;
  update public.map_studio_drafts set document=target.document,revision=revision+1,updated_by=p_actor,updated_at=now() where map_key=p_map_key;
  update public.map_studio_projects set published_version_id=target.id,updated_at=now() where map_key=p_map_key;
  result:=jsonb_build_object('version_id',target.id); insert into public.map_studio_idempotency(map_key,user_id,operation,idempotency_key,request_fingerprint,response) values(p_map_key,p_actor,'rollback',p_idempotency_key,request_fingerprint,result);
  insert into public.map_studio_audit_events(map_key,actor_id,action,entity_id,metadata) values(p_map_key,p_actor,'rollback',target.id::text,jsonb_build_object('revision',d.revision+1));
  return result;
end $$;

create or replace function public.map_studio_asset_list(p_map_key text,p_actor uuid)
returns setof public.map_studio_assets language sql stable security definer set search_path=public,pg_temp
as $$ select a.* from public.map_studio_assets a where a.map_key=p_map_key and a.state<>'deleted' and public.map_studio_member(p_map_key,p_actor) order by a.created_at desc $$;
create or replace function public.map_studio_asset_get(p_map_key text,p_asset_id uuid,p_actor uuid)
returns public.map_studio_assets language sql stable security definer set search_path=public,pg_temp
as $$ select a.* from public.map_studio_assets a where a.map_key=p_map_key and a.id=p_asset_id and a.state<>'deleted' and public.map_studio_member(p_map_key,p_actor) $$;
create or replace function public.map_studio_asset_register(p_map_key text,p_asset jsonb,p_actor uuid)
returns public.map_studio_assets language plpgsql security definer set search_path=public,pg_temp
as $$ declare p public.map_studio_projects; result public.map_studio_assets; asset_id uuid; original_path text; processed_path text; digest text;
begin
  select * into p from public.map_studio_projects where map_key=p_map_key and not disabled for update; if not found then raise exception 'project_not_found' using errcode='P0002'; end if;
  if p_actor is null or not public.map_studio_member(p_map_key,p_actor) then raise exception 'membership_required' using errcode='42501'; end if;
  asset_id:=nullif(p_asset->>'id','')::uuid; digest:=coalesce(p_asset->>'sha256','');
  original_path:=coalesce(p_asset->>'originalPath',p_asset->>'original_path'); processed_path:=coalesce(p_asset->>'processedPath',p_asset->>'processed_path');
  if asset_id is null or original_path is distinct from p_map_key||'/'||asset_id::text||'/original'
     or processed_path is distinct from p_map_key||'/'||asset_id::text||'/'||digest||'.webp' then raise exception 'asset_path_invalid' using errcode='22023'; end if;
  insert into public.map_studio_assets(id,map_key,created_by,name,alt_text,rights,mime_type,sha256,original_path,processed_path,width,height,byte_size,state)
  values(asset_id,p_map_key,p_actor,p_asset->>'name',coalesce(p_asset->>'altText',p_asset->>'alt_text'),p_asset->>'rights',coalesce(p_asset->>'mimeType',p_asset->>'mime_type'),digest,original_path,processed_path,nullif(p_asset->>'width','')::integer,nullif(p_asset->>'height','')::integer,nullif(coalesce(p_asset->>'byteSize',p_asset->>'byte_size'),'')::bigint,coalesce(p_asset->>'state','pending')) returning * into result;
  insert into public.map_studio_audit_events(map_key,actor_id,action,entity_id,metadata) values(p_map_key,p_actor,'asset_register',asset_id::text,jsonb_build_object('sha256',digest,'state',result.state));
  return result;
end $$;
create or replace function public.map_studio_asset_delete(p_map_key text,p_asset_id uuid,p_actor uuid)
returns jsonb language plpgsql security definer set search_path=public,pg_temp
as $$ declare p public.map_studio_projects;
begin
  select * into p from public.map_studio_projects where map_key=p_map_key and not disabled for update; if not found then raise exception 'project_not_found' using errcode='P0002'; end if;
  if p_actor is null or not public.map_studio_member(p_map_key,p_actor) then raise exception 'membership_required' using errcode='42501'; end if;
  if exists(select 1 from public.map_studio_drafts d,jsonb_array_elements(d.document->'layers') x where d.map_key=p_map_key and x->>'assetId'=p_asset_id::text)
     or exists(select 1 from public.map_studio_versions v,jsonb_array_elements(v.document->'layers') x where v.map_key=p_map_key and x->>'assetId'=p_asset_id::text) then raise exception 'asset_referenced' using errcode='40901'; end if;
  update public.map_studio_assets set state='deleted' where map_key=p_map_key and id=p_asset_id and state<>'deleted';
  if not found then raise exception 'asset_not_found' using errcode='P0002'; end if;
  insert into public.map_studio_audit_events(map_key,actor_id,action,entity_id) values(p_map_key,p_actor,'asset_delete',p_asset_id::text);
  return jsonb_build_object('ok',true);
end $$;

create or replace function public.map_studio_set_member(p_map_key text,p_user_id uuid,p_enabled boolean,p_actor uuid)
returns jsonb language plpgsql security definer set search_path=public,pg_temp
as $$ declare p public.map_studio_projects;
begin
  if p_actor is null or not public.map_studio_owner(p_actor) then raise exception 'admin_required' using errcode='42501'; end if;
  if p_user_id is distinct from p_actor then raise exception 'owner_required' using errcode='42501'; end if;
  select * into p from public.map_studio_projects where map_key=p_map_key for update; if not found then raise exception 'project_not_found' using errcode='P0002'; end if;
  insert into public.map_studio_members(map_key,user_id,enabled,updated_at) values(p_map_key,p_user_id,p_enabled,now()) on conflict(map_key,user_id) do update set enabled=excluded.enabled,updated_at=now();
  insert into public.map_studio_audit_events(map_key,actor_id,action,entity_id,metadata) values(p_map_key,p_actor,'member_set',p_user_id::text,jsonb_build_object('enabled',p_enabled));
  return jsonb_build_object('ok',true);
end $$;
create or replace function public.map_studio_disable_project(p_map_key text,p_actor uuid)
returns jsonb language plpgsql security definer set search_path=public,pg_temp
as $$ begin
  if p_actor is null or not public.map_studio_owner(p_actor) then raise exception 'admin_required' using errcode='42501'; end if;
  update public.map_studio_projects set disabled=true,updated_at=now() where map_key=p_map_key; if not found then raise exception 'project_not_found' using errcode='P0002'; end if;
  insert into public.map_studio_audit_events(map_key,actor_id,action) values(p_map_key,p_actor,'disable');
  return jsonb_build_object('ok',true);
end $$;

create or replace function public.map_studio_public_manifest(p_map_key text)
returns jsonb language sql stable security definer set search_path=public,pg_temp
as $$ select jsonb_build_object('version_id',v.id,'document',v.document,'assets',v.assets)
from public.map_studio_projects p join public.map_studio_versions v on v.id=p.published_version_id where p.map_key=p_map_key and not p.disabled $$;


create or replace function public.map_studio_owner_check(p_actor uuid)
returns jsonb language sql stable security definer set search_path=public,pg_temp
as $$ select jsonb_build_object('isOwner',public.map_studio_owner(p_actor)) $$;

do $$ declare t text; begin
  foreach t in array array['map_studio_owners','map_studio_projects','map_studio_members','map_studio_businesses','map_studio_drafts','map_studio_leases','map_studio_versions','map_studio_assets','map_studio_idempotency','map_studio_audit_events'] loop
    execute format('alter table public.%I enable row level security',t);
    execute format('revoke all on public.%I from public,anon,authenticated,service_role',t);
  end loop;
end $$;

revoke all on function public.map_studio_register_project(jsonb,jsonb,jsonb,uuid,text) from public,anon,authenticated;
revoke all on function public.map_studio_public_manifest(text) from public,anon,authenticated;
revoke all on function public.map_studio_list_projects(uuid) from public,anon,authenticated;
revoke all on function public.map_studio_get_project(text,uuid) from public,anon,authenticated;
revoke all on function public.map_studio_project(text,uuid) from public,anon,authenticated;
revoke all on function public.map_studio_acquire_lease(text,text,uuid) from public,anon,authenticated;
revoke all on function public.map_studio_release_lease(text,text,uuid) from public,anon,authenticated;
revoke all on function public.map_studio_save_draft(text,jsonb,bigint,text,uuid) from public,anon,authenticated;
revoke all on function public.map_studio_list_versions(text,uuid) from public,anon,authenticated;
revoke all on function public.map_studio_publish(text,bigint,text,text,jsonb,uuid) from public,anon,authenticated;
revoke all on function public.map_studio_rollback(text,uuid,text,text,uuid) from public,anon,authenticated;
revoke all on function public.map_studio_asset_list(text,uuid) from public,anon,authenticated;
revoke all on function public.map_studio_asset_get(text,uuid,uuid) from public,anon,authenticated;
revoke all on function public.map_studio_asset_register(text,jsonb,uuid) from public,anon,authenticated;
revoke all on function public.map_studio_asset_delete(text,uuid,uuid) from public,anon,authenticated;
revoke all on function public.map_studio_set_member(text,uuid,boolean,uuid) from public,anon,authenticated;
revoke all on function public.map_studio_disable_project(text,uuid) from public,anon,authenticated;
revoke all on function public.map_studio_owner_check(uuid) from public,anon,authenticated;
grant execute on function public.map_studio_register_project(jsonb,jsonb,jsonb,uuid,text) to service_role;
grant execute on function public.map_studio_public_manifest(text) to service_role;
grant execute on function public.map_studio_list_projects(uuid) to service_role;
grant execute on function public.map_studio_get_project(text,uuid) to service_role;
grant execute on function public.map_studio_project(text,uuid) to service_role;
grant execute on function public.map_studio_acquire_lease(text,text,uuid) to service_role;
grant execute on function public.map_studio_release_lease(text,text,uuid) to service_role;
grant execute on function public.map_studio_save_draft(text,jsonb,bigint,text,uuid) to service_role;
grant execute on function public.map_studio_list_versions(text,uuid) to service_role;
grant execute on function public.map_studio_publish(text,bigint,text,text,jsonb,uuid) to service_role;
grant execute on function public.map_studio_rollback(text,uuid,text,text,uuid) to service_role;
grant execute on function public.map_studio_asset_list(text,uuid) to service_role;
grant execute on function public.map_studio_asset_get(text,uuid,uuid) to service_role;
grant execute on function public.map_studio_asset_register(text,jsonb,uuid) to service_role;
grant execute on function public.map_studio_asset_delete(text,uuid,uuid) to service_role;
grant execute on function public.map_studio_set_member(text,uuid,boolean,uuid) to service_role;
grant execute on function public.map_studio_disable_project(text,uuid) to service_role;
grant execute on function public.map_studio_owner_check(uuid) to service_role;


grant execute on function public.map_studio_member(text,uuid) to service_role;
grant execute on function public.map_studio_owner(uuid) to service_role;
grant execute on function public.map_studio_document_valid(jsonb,text) to service_role;

-- k.apt cloud v1. Run once in Supabase > SQL Editor. Safe to rerun.
-- Dedicated names keep an existing program's tables, policies and buckets intact.
begin;
create table if not exists public.kapt_workspaces (
 user_id uuid primary key references auth.users(id) on delete cascade,
 revision bigint not null default 1 check (revision > 0),
 payload jsonb not null check (jsonb_typeof(payload)='object' and payload->>'schema'='1' and octet_length(payload::text)<=4194304),
 updated_at timestamptz not null default now()
);
alter table public.kapt_workspaces enable row level security;
revoke all on public.kapt_workspaces from anon;
grant select,insert,update on public.kapt_workspaces to authenticated;
drop policy if exists kapt_owner_select on public.kapt_workspaces;
create policy kapt_owner_select on public.kapt_workspaces for select to authenticated using ((select auth.uid())=user_id);
drop policy if exists kapt_owner_insert on public.kapt_workspaces;
create policy kapt_owner_insert on public.kapt_workspaces for insert to authenticated with check ((select auth.uid())=user_id);
drop policy if exists kapt_owner_update on public.kapt_workspaces;
create policy kapt_owner_update on public.kapt_workspaces for update to authenticated using ((select auth.uid())=user_id) with check ((select auth.uid())=user_id);
create or replace function public.kapt_write_workspace(p_expected_revision bigint,p_payload jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare v_uid uuid:=auth.uid();v_current public.kapt_workspaces%rowtype;v_result jsonb;
begin
 if v_uid is null then raise exception 'Login required' using errcode='42501';end if;
 if jsonb_typeof(p_payload) is distinct from 'object' or p_payload->>'schema' is distinct from '1' or octet_length(p_payload::text)>4194304 then raise exception 'Invalid workspace payload';end if;
 -- Serialize initial inserts as well as later updates for this user only.
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(v_uid::text,91731));
 select * into v_current from public.kapt_workspaces where user_id=v_uid for update;
 if coalesce(v_current.revision,0)<>p_expected_revision then
  return jsonb_build_object('conflict',true,'revision',coalesce(v_current.revision,0),'payload',v_current.payload);
 end if;
 insert into public.kapt_workspaces(user_id,revision,payload,updated_at) values(v_uid,1,p_payload,now())
 on conflict(user_id) do update set revision=kapt_workspaces.revision+1,payload=excluded.payload,updated_at=now()
 returning jsonb_build_object('revision',revision,'payload',payload) into v_result;
 return v_result;
end;$$;
revoke all on function public.kapt_write_workspace(bigint,jsonb) from public,anon;
grant execute on function public.kapt_write_workspace(bigint,jsonb) to authenticated;
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values('kapt-private-images','kapt-private-images',false,31457280,array['image/png','image/jpeg','image/webp','image/gif'])
on conflict(id) do nothing;
-- Reused buckets must already be private. Stop instead of changing unrelated settings.
do $$begin if exists(select 1 from storage.buckets where id='kapt-private-images' and public=true) then raise exception 'kapt-private-images must be private';end if;end;$$;
drop policy if exists kapt_image_select on storage.objects;
create policy kapt_image_select on storage.objects for select to authenticated using(bucket_id='kapt-private-images' and (storage.foldername(name))[1]=(select auth.uid())::text);
drop policy if exists kapt_image_insert on storage.objects;
create policy kapt_image_insert on storage.objects for insert to authenticated with check(bucket_id='kapt-private-images' and (storage.foldername(name))[1]=(select auth.uid())::text);
drop policy if exists kapt_image_update on storage.objects;
create policy kapt_image_update on storage.objects for update to authenticated using(bucket_id='kapt-private-images' and (storage.foldername(name))[1]=(select auth.uid())::text) with check(bucket_id='kapt-private-images' and (storage.foldername(name))[1]=(select auth.uid())::text);
drop policy if exists kapt_image_delete on storage.objects;
create policy kapt_image_delete on storage.objects for delete to authenticated using(bucket_id='kapt-private-images' and (storage.foldername(name))[1]=(select auth.uid())::text);
commit;

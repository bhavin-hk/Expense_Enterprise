
-- Insert the bucket into storage.buckets
insert into storage.buckets (id, name, public)
values ('avatars', 'avatars', true);

-- Policy: Allow public read access to avatar images
create policy "Public Access"
  on storage.objects for select
  using ( bucket_id = 'avatars' );

-- Policy: Allow authenticated users to upload invalidating their own folder path
-- Ideally we check path, but for now just authenticated insert is a good start.
create policy "Authenticated Upload"
  on storage.objects for insert
  with check ( bucket_id = 'avatars' and auth.role() = 'authenticated' );

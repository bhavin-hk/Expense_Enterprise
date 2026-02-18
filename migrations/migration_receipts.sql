-- Add receipt_url column to expenses table
alter table public.expenses add column if not exists receipt_url text;

-- Create receipts bucket
insert into storage.buckets (id, name, public)
values ('receipts', 'receipts', true)
on conflict (id) do nothing;

-- Policies for receipts bucket
create policy "Public Access Receipts"
  on storage.objects for select
  using ( bucket_id = 'receipts' );

create policy "Authenticated Upload Receipts"
  on storage.objects for insert
  with check ( bucket_id = 'receipts' and auth.role() = 'authenticated' );

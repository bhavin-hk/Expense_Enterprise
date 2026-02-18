-- Create a table for user-defined categories
create table public.user_categories (
    id uuid default gen_random_uuid() primary key,
    user_id uuid references public.profiles(id) not null,
    name text not null,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

-- Enable RLS
alter table public.user_categories enable row level security;

-- Policies
create policy "Users can view their own categories." on public.user_categories
  for select using (auth.uid() = user_id);

create policy "Users can insert their own categories." on public.user_categories
  for insert with check (auth.uid() = user_id);

create policy "Users can delete their own categories." on public.user_categories
  for delete using (auth.uid() = user_id);

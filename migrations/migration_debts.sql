-- Create debts table
create table public.debts (
    id uuid default gen_random_uuid() primary key,
    user_id uuid references public.profiles(id) not null,
    person_name text not null,
    amount numeric not null,
    type text not null check (type in ('lend', 'borrow')),
    status text default 'active' check (status in ('active', 'settled')),
    due_date date,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

alter table public.debts enable row level security;

create policy "Users can manage their own debts." on public.debts
  for all using (auth.uid() = user_id);

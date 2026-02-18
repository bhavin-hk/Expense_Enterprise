-- Create a table for public profiles, linked to the auth.users table
create table public.profiles (
  id uuid references auth.users not null primary key,
  updated_at timestamp with time zone,
  full_name text,
  avatar_url text,
  website text,

  constraint username_length check (char_length(full_name) >= 3)
);

-- Set up Row Level Security (RLS)
-- See https://supabase.com/docs/guides/auth/row-level-security for more details.
alter table public.profiles enable row level security;

create policy "Public profiles are viewable by everyone." on public.profiles
  for select using (true);

create policy "Users can insert their own profile." on public.profiles
  for insert with check (auth.uid() = id);

create policy "Users can update own profile." on public.profiles
  for update using (auth.uid() = id);

-- Create a table for bank details
create table public.bank_accounts (
    id uuid default gen_random_uuid() primary key,
    user_id uuid references public.profiles(id) not null,
    bank_name text not null,
    account_number text not null,
    ifsc_code text not null,
    opening_balance numeric default 0,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

alter table public.bank_accounts enable row level security;

create policy "Users can view their own bank accounts." on public.bank_accounts
  for select using (auth.uid() = user_id);

create policy "Users can insert their own bank accounts." on public.bank_accounts
  for insert with check (auth.uid() = user_id);

create policy "Users can delete their own bank accounts." on public.bank_accounts
  for delete using (auth.uid() = user_id);

create policy "Users can update their own bank accounts." on public.bank_accounts
  for update using (auth.uid() = user_id);

-- Function to handle new user signup
create or replace function public.handle_new_user()
returns trigger as $$
begin
  insert into public.profiles (id, full_name, avatar_url)
  values (new.id, new.raw_user_meta_data->>'full_name', new.raw_user_meta_data->>'avatar_url');
  return new;
end;
$$ language plpgsql security definer;

-- Trigger to call the function on new user creation
create or replace trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

-- Add budget and currency columns to profiles
alter table public.profiles add column if not exists budget numeric default 0;
alter table public.profiles add column if not exists currency text default '₹';

-- Create expenses table
create table public.expenses (
    id uuid default gen_random_uuid() primary key,
    user_id uuid references public.profiles(id) not null,
    date date not null,
    category text not null,
    amount numeric not null,
    description text,
    debt_id uuid references public.debts(id) on delete cascade,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

alter table public.expenses enable row level security;

create policy "Users can view their own expenses." on public.expenses
  for select using (auth.uid() = user_id);

create policy "Users can insert their own expenses." on public.expenses
  for insert with check (auth.uid() = user_id);

create policy "Users can update their own expenses." on public.expenses
  for update using (auth.uid() = user_id);

create policy "Users can delete their own expenses." on public.expenses
  for delete using (auth.uid() = user_id);

-- Create recurring_expenses table
create table public.recurring_expenses (
    id uuid default gen_random_uuid() primary key,
    user_id uuid references public.profiles(id) not null,
    category text not null,
    amount numeric not null,
    description text,
    next_due_date date not null,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

alter table public.recurring_expenses enable row level security;

create policy "Users can manage their own recurring expenses." on public.recurring_expenses
  for all using (auth.uid() = user_id);

-- Create debts table
create table public.debts (
    id uuid default gen_random_uuid() primary key,
    user_id uuid references public.profiles(id) not null,
    person_name text not null,
    amount numeric not null,
    type text not null check (type in ('lend', 'borrow')),
    status text default 'active' check (status in ('active', 'settled')),
    transaction_date date not null default current_date,
    description text,
    due_date date,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

alter table public.debts enable row level security;

create policy "Users can manage their own debts." on public.debts
  for all using (auth.uid() = user_id);
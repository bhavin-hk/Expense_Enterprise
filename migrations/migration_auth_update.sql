-- Add username and email columns to profiles table
alter table public.profiles add column if not exists username text unique;
alter table public.profiles add column if not exists email text;

-- Update the handle_new_user function to include username and email
create or replace function public.handle_new_user()
returns trigger as $$
begin
  insert into public.profiles (id, full_name, avatar_url, username, email)
  values (
    new.id, 
    new.raw_user_meta_data->>'full_name', 
    new.raw_user_meta_data->>'avatar_url',
    new.raw_user_meta_data->>'username',
    new.email
  );
  return new;
end;
$$ language plpgsql security definer;

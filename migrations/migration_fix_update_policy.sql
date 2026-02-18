-- Run this in Supabase SQL Editor to allow editing bank accounts
create policy "Users can update their own bank accounts." on public.bank_accounts
  for update using (auth.uid() = user_id);

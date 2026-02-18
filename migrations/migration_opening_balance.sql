-- Run this in your Supabase SQL Editor to add the opening_balance column
alter table public.bank_accounts add column if not exists opening_balance numeric default 0;

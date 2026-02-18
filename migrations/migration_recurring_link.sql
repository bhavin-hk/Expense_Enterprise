-- Add recurring_rule_id to expenses table
-- We use ON DELETE SET NULL to ensure that if a rule is deleted, the history remains but the link is cleared (showing it's no longer active)
ALTER TABLE public.expenses 
ADD COLUMN recurring_rule_id uuid REFERENCES public.recurring_expenses(id) ON DELETE SET NULL;

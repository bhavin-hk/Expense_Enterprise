-- 1. Mock Supabase Auth Schema & Functions
-- This allows RLS policies using auth.uid() to work locally
CREATE SCHEMA IF NOT EXISTS auth;

CREATE OR REPLACE FUNCTION auth.uid() 
RETURNS UUID AS $$
    -- In local testing, we return a fixed ID for the "Local Admin"
    SELECT '00000000-0000-0000-0000-000000000001'::UUID;
$$ LANGUAGE SQL STABLE;

CREATE OR REPLACE FUNCTION auth.jwt() 
RETURNS JSONB AS $$
    SELECT jsonb_build_object('sub', '00000000-0000-0000-0000-000000000001');
$$ LANGUAGE SQL STABLE;

-- 2. Profiles Table (Simulates the main application's profiles)
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name TEXT,
    email TEXT UNIQUE,
    currency TEXT DEFAULT '₹',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 3. Enterprise Organizations
CREATE TABLE IF NOT EXISTS public.ent_organizations (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 4. Enterprise Members
CREATE TABLE IF NOT EXISTS public.ent_members (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    organization_id UUID REFERENCES public.ent_organizations(id) ON DELETE CASCADE NOT NULL,
    user_id UUID REFERENCES public.profiles(id) NOT NULL,
    role TEXT DEFAULT 'member' CHECK (role IN ('admin', 'member', 'viewer')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    UNIQUE(organization_id, user_id)
);

-- 5. Enterprise Revenue
CREATE TABLE IF NOT EXISTS public.ent_revenue (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    organization_id UUID REFERENCES public.ent_organizations(id) ON DELETE CASCADE NOT NULL,
    amount NUMERIC NOT NULL DEFAULT 0,
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    status TEXT DEFAULT 'completed' CHECK (status IN ('pending', 'completed', 'cancelled')),
    taken_by UUID REFERENCES public.profiles(id),
    method TEXT,
    bank_account_id UUID REFERENCES public.enterprise_bank_accounts(id),
    narrative TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 6. Enterprise Expenses
CREATE TABLE IF NOT EXISTS public.ent_expenses (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    organization_id UUID REFERENCES public.ent_organizations(id) ON DELETE CASCADE NOT NULL,
    amount NUMERIC NOT NULL DEFAULT 0,
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    category TEXT NOT NULL,
    taken_by UUID REFERENCES public.profiles(id),
    method TEXT,
    bank_account_id UUID REFERENCES public.enterprise_bank_accounts(id),
    narrative TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 7. Enterprise Investments
CREATE TABLE IF NOT EXISTS public.ent_investments (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    organization_id UUID REFERENCES public.ent_organizations(id) ON DELETE CASCADE NOT NULL,
    amount NUMERIC NOT NULL DEFAULT 0,
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    source TEXT,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 8. Enterprise Bank Accounts (Current & CC/OD) — Local Only
CREATE TABLE IF NOT EXISTS public.enterprise_bank_accounts (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES public.profiles(id) NOT NULL,
    business_name TEXT NOT NULL,
    bank_name TEXT NOT NULL,
    account_number TEXT NOT NULL,
    ifsc_code TEXT NOT NULL,
    opening_balance NUMERIC(15,2) DEFAULT 0.00,
    account_type TEXT CHECK (account_type IN ('Current', 'CC/OD')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 9. Enable Row Level Security (Mimics Supabase)
ALTER TABLE public.ent_organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ent_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ent_revenue ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ent_expenses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ent_investments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.enterprise_bank_accounts ENABLE ROW LEVEL SECURITY;

-- 9. Basic RLS Policies (Local PG variant)
CREATE POLICY "Users can view orgs they belong to" ON public.ent_organizations
    FOR SELECT USING (EXISTS (SELECT 1 FROM public.ent_members WHERE organization_id = ent_organizations.id AND user_id = auth.uid()));

CREATE POLICY "Members can manage revenue" ON public.ent_revenue
    FOR ALL USING (EXISTS (SELECT 1 FROM public.ent_members WHERE organization_id = ent_revenue.organization_id AND user_id = auth.uid()));

CREATE POLICY "Members can manage expenses" ON public.ent_expenses
    FOR ALL USING (EXISTS (SELECT 1 FROM public.ent_members WHERE organization_id = ent_expenses.organization_id AND user_id = auth.uid()));

CREATE POLICY "Members can manage investments" ON public.ent_investments
    FOR ALL USING (EXISTS (SELECT 1 FROM public.ent_members WHERE organization_id = ent_investments.organization_id AND user_id = auth.uid()));

-- 10. SEED DATA (For Immediate Verification)
DO $$
DECLARE
    org_id UUID;
    member_user_id UUID := '00000000-0000-0000-0000-000000000001'::UUID;
BEGIN
    -- Create Mock Profile
    INSERT INTO public.profiles (id, full_name, email) 
    VALUES (member_user_id, 'Local Admin', 'admin@local.test')
    ON CONFLICT (id) DO NOTHING;

    -- Create Mock Organization
    INSERT INTO public.ent_organizations (name) 
    VALUES ('Acme Corp Local') 
    RETURNING id INTO org_id;

    -- Create Membership
    INSERT INTO public.ent_members (organization_id, user_id, role)
    VALUES (org_id, member_user_id, 'admin');

    -- Add some initial data
    INSERT INTO public.ent_revenue (organization_id, amount, description) VALUES (org_id, 50000, 'Initial Funding');
    INSERT INTO public.ent_expenses (organization_id, amount, category, description) VALUES (org_id, 1200, 'Software', 'Server Costs');
END $$;

-- 11. Enterprise Credentials (Per-Business Authentication)
CREATE TABLE IF NOT EXISTS public.enterprise_credentials (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES public.profiles(id) NOT NULL,
    business_name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_verified BOOLEAN DEFAULT FALSE,
    verification_token TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    UNIQUE(user_id, business_name)
);

ALTER TABLE public.enterprise_credentials ENABLE ROW LEVEL SECURITY;

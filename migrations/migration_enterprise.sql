-- Enterprise Management Module Migration

-- 1. Create Organizations Table
CREATE TABLE IF NOT EXISTS public.ent_organizations (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 2. Create Members Table (Linking users to organizations)
CREATE TABLE IF NOT EXISTS public.ent_members (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    organization_id UUID REFERENCES public.ent_organizations(id) ON DELETE CASCADE NOT NULL,
    user_id UUID REFERENCES public.profiles(id) NOT NULL,
    role TEXT DEFAULT 'member' CHECK (role IN ('admin', 'member', 'viewer')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    UNIQUE(organization_id, user_id)
);

-- 3. Create Enterprise Revenue Table
CREATE TABLE IF NOT EXISTS public.ent_revenue (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    organization_id UUID REFERENCES public.ent_organizations(id) ON DELETE CASCADE NOT NULL,
    amount NUMERIC NOT NULL DEFAULT 0,
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    status TEXT DEFAULT 'completed' CHECK (status IN ('pending', 'completed', 'cancelled')),
    taken_by UUID REFERENCES public.profiles(id),
    method TEXT,
    narrative TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 4. Create Enterprise Expenses Table
CREATE TABLE IF NOT EXISTS public.ent_expenses (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    organization_id UUID REFERENCES public.ent_organizations(id) ON DELETE CASCADE NOT NULL,
    amount NUMERIC NOT NULL DEFAULT 0,
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    category TEXT NOT NULL,
    taken_by UUID REFERENCES public.profiles(id),
    method TEXT,
    narrative TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 5. Create Enterprise Investments Table
CREATE TABLE IF NOT EXISTS public.ent_investments (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    organization_id UUID REFERENCES public.ent_organizations(id) ON DELETE CASCADE NOT NULL,
    amount NUMERIC NOT NULL DEFAULT 0,
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    source TEXT,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Enable RLS
ALTER TABLE public.ent_organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ent_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ent_revenue ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ent_expenses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ent_investments ENABLE ROW LEVEL SECURITY;

-- 6. RLS Policies

-- ORGS: View organizations you are a member of
CREATE POLICY "Users can view orgs they belong to" ON public.ent_organizations
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.ent_members 
            WHERE ent_members.organization_id = ent_organizations.id 
            AND ent_members.user_id = auth.uid()
        )
    );

-- MEMBERS: View members of your organizations
CREATE POLICY "Members can view other members in same org" ON public.ent_members
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.ent_members AS me
            WHERE me.organization_id = public.ent_members.organization_id
            AND me.user_id = auth.uid()
        )
    );

-- REVENUE: Manage revenue for your organizations
CREATE POLICY "Members can manage revenue" ON public.ent_revenue
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM public.ent_members
            WHERE ent_members.organization_id = public.ent_revenue.organization_id
            AND ent_members.user_id = auth.uid()
        )
    );

-- EXPENSES: Manage expenses for your organizations
CREATE POLICY "Members can manage expenses" ON public.ent_expenses
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM public.ent_members
            WHERE ent_members.organization_id = public.ent_expenses.organization_id
            AND ent_members.user_id = auth.uid()
        )
    );

-- INVESTMENTS: Manage investments for your organizations
CREATE POLICY "Members can manage investments" ON public.ent_investments
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM public.ent_members
            WHERE ent_members.organization_id = public.ent_investments.organization_id
            AND ent_members.user_id = auth.uid()
        )
    );

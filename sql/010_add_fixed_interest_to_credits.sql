-- Add fixed_interest_amount column to credits table
-- When set, the credit uses a fixed total interest (e.g. for installment purchases)
-- instead of daily accruing interest based on effective_yearly_rate.

ALTER TABLE credits ADD COLUMN fixed_interest_amount NUMERIC(12,2);

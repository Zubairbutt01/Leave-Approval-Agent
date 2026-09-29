-- Run this ONCE in Supabase -> SQL Editor. Do NOT run the old schema.sql again.

-- 1. Remove the old trigger (it only worked when a request became 'Approved').
DROP TRIGGER IF EXISTS update_annual_leave_balances ON leave_requests;
DROP FUNCTION IF EXISTS handle_annual_leave_balance();

-- 2. New logic:
--    * New request (Pending)            -> days are taken off the balance immediately
--    * Pending -> Approved              -> nothing (days were already taken)
--    * Pending/Approved -> Rejected     -> days are given back
--    * Pending/Approved -> Cancelled    -> days are given back
CREATE OR REPLACE FUNCTION handle_annual_leave_balance()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status IN ('Pending', 'Approved') THEN
            UPDATE employees
            SET annual_leave_balance = annual_leave_balance - NEW.total_days
            WHERE employee_id = NEW.employee_id;
        END IF;
        RETURN NEW;
    END IF;

    -- TG_OP = 'UPDATE'
    IF OLD.status IN ('Pending', 'Approved')
       AND NEW.status IN ('Rejected', 'Cancelled') THEN
        UPDATE employees
        SET annual_leave_balance = annual_leave_balance + NEW.total_days
        WHERE employee_id = NEW.employee_id;

    ELSIF OLD.status IN ('Rejected', 'Cancelled')
       AND NEW.status IN ('Pending', 'Approved') THEN
        UPDATE employees
        SET annual_leave_balance = annual_leave_balance - NEW.total_days
        WHERE employee_id = NEW.employee_id;
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER update_annual_leave_balances
AFTER INSERT OR UPDATE ON leave_requests
FOR EACH ROW
EXECUTE FUNCTION handle_annual_leave_balance();

-- 3. Clean your old test data for E005 so the test starts fresh at 14 days.
DELETE FROM leave_requests WHERE employee_id = 'E005';
UPDATE employees SET annual_leave_balance = 14 WHERE employee_id = 'E005';

-- 1. Drop existing tables cleanly
DROP TABLE IF EXISTS leave_requests CASCADE;
DROP TABLE IF EXISTS employees CASCADE;
DROP TABLE IF EXISTS leave_types CASCADE;
DROP TABLE IF EXISTS departments CASCADE;

-- 2. Create tables (Only Annual Leave System)
CREATE TABLE departments (
    department_id INT PRIMARY KEY,
    department_name VARCHAR(100) NOT NULL
);

CREATE TABLE leave_types (
    leave_type_id INT PRIMARY KEY,
    type_name VARCHAR(50) NOT NULL,
    total_allowed_days INT NOT NULL
);

CREATE TABLE employees (
    employee_id VARCHAR(10) PRIMARY KEY, -- Changed to VARCHAR for 'E001' format
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    department_id INT,
    annual_leave_balance INT DEFAULT 14, -- Only Annual Leave
    FOREIGN KEY (department_id) REFERENCES departments(department_id)
);

CREATE TABLE leave_requests (
    request_id SERIAL PRIMARY KEY, -- Auto-increments (1, 2, 3...)
    employee_id VARCHAR(10),       -- Must match employees table type
    leave_type_id INT DEFAULT 1,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    total_days INT NOT NULL,
    status VARCHAR(20) DEFAULT 'Pending',
    reason TEXT,
    request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (employee_id) REFERENCES employees(employee_id),
    FOREIGN KEY (leave_type_id) REFERENCES leave_types(leave_type_id)
);

-- 3. Create Automated Trigger for Annual Leave Balance
CREATE OR REPLACE FUNCTION handle_annual_leave_balance()
RETURNS TRIGGER AS $$
BEGIN
    -- Deduct balance when leave is approved
    IF NEW.status = 'Approved' AND OLD.status != 'Approved' THEN
        UPDATE employees 
        SET annual_leave_balance = annual_leave_balance - NEW.total_days 
        WHERE employee_id = NEW.employee_id;
    END IF;

    -- Refund balance if an approved leave is later rejected or cancelled
    IF (NEW.status = 'Rejected' OR NEW.status = 'Cancelled') AND OLD.status = 'Approved' THEN
        UPDATE employees 
        SET annual_leave_balance = annual_leave_balance + NEW.total_days 
        WHERE employee_id = NEW.employee_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_annual_leave_balances
AFTER UPDATE ON leave_requests
FOR EACH ROW
EXECUTE FUNCTION handle_annual_leave_balance();

-- 4. Insert Fake Data
INSERT INTO departments (department_id, department_name) VALUES
(1, 'Executive'), 
(2, 'Engineering'), 
(3, 'Human Resources'),
(4, 'Sales & Marketing');

-- Only one leave type exists now
INSERT INTO leave_types (leave_type_id, type_name, total_allowed_days) VALUES
(1, 'Annual Leave', 14);

-- Fake employees with alphanumeric IDs
INSERT INTO employees (employee_id, first_name, last_name, email, department_id, annual_leave_balance) VALUES
('E001', 'Kamran', 'Ahmed', 'kamran@company.pk', 1, 14),
('E002', 'Bilal', 'Tariq', 'bilal@company.pk', 2, 10), -- Used 4 days previously
('E003', 'Ali', 'Raza', 'ali@company.pk', 2, 14),
('E004', 'Fatima', 'Ali', 'fatima@company.pk', 2, 2),  -- Used 12 days previously
('E005', 'Ayesha', 'Khan', 'ayesha@company.pk', 3, 14),
('E006', 'Usman', 'Sheikh', 'usman@company.pk', 4, 7); -- Used 7 days previously

-- Leave Requests table remains completely empty for the Agent to use!
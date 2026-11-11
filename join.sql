create database emp_db;
use emp_db;

create table employee(emp_id int primary key, emp_name varchar(20), salary int, manager_id int);
insert into employee values(1,"A",80000,3),(2,"B",90000,3),(3,"C",75000,2),(4,"D",83000,NULL);


-- FIND EMPLOYEES WHO EARN MORE THAN their manager
SELECT emp_name, salary
FROM employee e
WHERE salary > (
    SELECT salary
    FROM employee m
    WHERE m.emp_id = e.manager_id
);

create table employees(emp_id int primary key, emp_name varchar(20), salary int);
insert into employees values(1,"A",50000),(2,"B",60000),(3,"C",70000),(4,"D",60000),(5,"E",70000);


select max(salary) from employees where salary < (select max(salary) from employees);









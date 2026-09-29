INSERT INTO customers (id, name, status, state, created_at) VALUES
    (1, 'Alice', 'A', 'TX', '2024-01-10'),
    (2, 'Bob', 'I', 'TX', '2024-02-01'),
    (3, 'Cara', 'A', 'CA', '2023-11-01'),
    (4, 'Test User', 'T', 'NY', '2024-03-01'),
    (5, 'Dan', 'A', 'TX', '2025-01-05');

INSERT INTO orders (id, customer_id, created_at) VALUES
    (1, 1, '2024-03-10'),
    (2, 1, '2024-06-01'),
    (3, 2, '2024-04-01'),
    (4, 3, '2024-05-15'),
    (5, 5, '2025-02-01');

INSERT INTO order_items (id, order_id, qty, unit_price) VALUES
    (1, 1, 2, 10.00),
    (2, 1, 1, 5.00),
    (3, 2, 4, 15.00),
    (4, 3, 1, 100.00),
    (5, 4, 3, 20.00),
    (6, 5, 2, 50.00);

INSERT INTO payments (id, order_id, amount, kind) VALUES
    (1, 1, 25.00, 'charge'),
    (2, 2, 60.00, 'charge'),
    (3, 2, 10.00, 'refund'),
    (4, 3, 100.00, 'charge'),
    (5, 4, 60.00, 'charge'),
    (6, 5, 100.00, 'charge');

SELECT setval('customers_id_seq', (SELECT MAX(id) FROM customers));
SELECT setval('orders_id_seq', (SELECT MAX(id) FROM orders));
SELECT setval('order_items_id_seq', (SELECT MAX(id) FROM order_items));
SELECT setval('payments_id_seq', (SELECT MAX(id) FROM payments));

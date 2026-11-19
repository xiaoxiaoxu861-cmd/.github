USE minimall_test;
INSERT INTO users (phone, password_hash) VALUES
('13800138001', '$2a$10$HEXlx430gyyFOlHT6GtBT.GqQ3FXOr9li4JVWlFgwiEqaEtobe.Ui'),
('13900139002', '$2a$10$HEXlx430gyyFOlHT6GtBT.GqQ3FXOr9li4JVWlFgwiEqaEtobe.Ui')
ON DUPLICATE KEY UPDATE password_hash=VALUES(password_hash), failed_attempts=0, locked_until=NULL;
INSERT INTO products (name, description, price, stock) VALUES
('无线蓝牙耳机', '蓝牙 5.3，适合日常通勤。', 199.00, 30),
('机械键盘', '87 键有线机械键盘。', 329.00, 15),
('无线鼠标', '静音办公鼠标。', 89.90, 50),
('显示器支架', '铝合金桌面显示器支架。', 159.00, 8),
('Type-C 数据线', '1 米快充数据线。', 29.90, 100),
('便携充电宝', '10000mAh 充电宝。', 129.00, 1),
('笔记本电脑包', '15.6 英寸防水电脑包。', 79.00, 12),
('游戏手柄', '目前缺货，等待补货。', 249.00, 0)
ON DUPLICATE KEY UPDATE name=VALUES(name);

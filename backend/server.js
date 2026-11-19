require('dotenv').config();
const express = require('express');
const mysql = require('mysql2/promise');
const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const logDir = path.join(root, 'logs');
fs.mkdirSync(logDir, { recursive: true });
const logFile = path.join(logDir, 'backend.log');
function log(level, message, data = {}) {
  fs.appendFileSync(logFile, `${new Date().toISOString()} [${level}] ${message} ${JSON.stringify(data)}\n`);
}
const db = mysql.createPool({ host: process.env.DB_HOST || '127.0.0.1', port: process.env.DB_PORT || 3306, user: process.env.DB_USER || 'root', password: process.env.DB_PASSWORD || '', database: process.env.DB_NAME || 'minimall_test', waitForConnections: true, connectionLimit: 10, decimalNumbers: true });
const app = express();
app.use(express.json());
app.use((req, res, next) => { const started = Date.now(); res.on('finish', () => log('INFO', `${req.method} ${req.path}`, { status: res.statusCode, ms: Date.now() - started })); next(); });
function auth(req, res, next) { try { req.user = jwt.verify((req.headers.authorization || '').replace('Bearer ', ''), process.env.JWT_SECRET || 'minimall-local-secret'); next(); } catch (_) { return res.status(401).json({ message: '请先登录' }); } }
function orderNo() { return `MM${Date.now()}${Math.floor(Math.random() * 900 + 100)}`; }
function details(order) { return db.query('SELECT id, product_id AS productId, product_name AS productName, unit_price AS unitPrice, quantity, subtotal FROM order_items WHERE order_id=?', [order.id]).then(([items]) => ({ ...order, items })); }

app.post('/api/auth/login', async (req, res, next) => {
  try {
    const { phone, password } = req.body;
    if (!/^\d{11}$/.test(phone || '') || !password || password.length < 6 || password.length > 20) return res.status(400).json({ message: '手机号或密码格式不正确' });
    const [rows] = await db.query('SELECT * FROM users WHERE phone=?', [phone]);
    const user = rows[0];
    if (!user) return res.status(401).json({ message: '手机号或密码错误' });
    if (user.locked_until && new Date(user.locked_until) > new Date()) return res.status(423).json({ message: '账号已锁定，请稍后再试' });
    if (!(await bcrypt.compare(password, user.password_hash))) {
      const attempts = user.failed_attempts + 1;
      const lockedUntil = attempts >= 5 ? new Date(Date.now() + 30 * 60 * 1000) : null;
      await db.query('UPDATE users SET failed_attempts=?, locked_until=? WHERE id=?', [attempts, lockedUntil, user.id]);
      return res.status(401).json({ message: '手机号或密码错误' });
    }
    await db.query('UPDATE users SET failed_attempts=0, locked_until=NULL WHERE id=?', [user.id]);
    const token = jwt.sign({ id: user.id, phone: user.phone }, process.env.JWT_SECRET || 'minimall-local-secret', { expiresIn: '8h' });
    res.json({ token, user: { id: user.id, phone: user.phone } });
  } catch (e) { next(e); }
});
app.get('/api/products', async (req, res, next) => { try { const keyword = req.query.keyword || ''; const [rows] = await db.query('SELECT id,name,description,price,stock FROM products WHERE name LIKE ? ORDER BY id', [`%${keyword}%`]); res.json(rows); } catch (e) { next(e); } });
app.get('/api/products/:id', async (req, res, next) => { try { const [rows] = await db.query('SELECT id,name,description,price,stock FROM products WHERE id=?', [req.params.id]); if (!rows[0]) return res.status(404).json({ message: '商品不存在' }); res.json(rows[0]); } catch (e) { next(e); } });

app.get('/api/cart', auth, async (req, res, next) => { try { const [rows] = await db.query('SELECT c.id,c.product_id AS productId,c.quantity,c.selected,p.name,p.price,p.stock,(c.quantity*p.price) AS subtotal FROM carts c JOIN products p ON c.product_id=p.id WHERE c.user_id=? ORDER BY c.id', [req.user.id]); const total = rows.filter(x => x.selected).reduce((sum, x) => sum + x.subtotal, 0); res.json({ items: rows, total }); } catch (e) { next(e); } });
app.post('/api/cart', auth, async (req, res, next) => { try { const { productId, quantity = 1 } = req.body; const [[product]] = await db.query('SELECT * FROM products WHERE id=?', [productId]); if (!product) return res.status(404).json({ message: '商品不存在' }); if (product.stock < 0) return res.status(400).json({ message: '商品缺货' }); const [[line]] = await db.query('SELECT * FROM carts WHERE user_id=? AND product_id=?', [req.user.id, productId]); const target = (line ? line.quantity : 0) + Number(quantity); if (target > product.stock) return res.status(400).json({ message: '数量超过库存' }); if (line) await db.query('UPDATE carts SET quantity=? WHERE id=?', [target, line.id]); else await db.query('INSERT INTO carts(user_id,product_id,quantity) VALUES(?,?,?)', [req.user.id, productId, quantity]); res.status(201).json({ message: '已加入购物车' }); } catch (e) { next(e); } });
app.patch('/api/cart/:id', auth, async (req, res, next) => { try { const { quantity, selected } = req.body; const [[line]] = await db.query('SELECT c.*,p.stock FROM carts c JOIN products p ON c.product_id=p.id WHERE c.id=? AND c.user_id=?', [req.params.id, req.user.id]); if (!line) return res.status(404).json({ message: '购物车商品不存在' }); if (quantity !== undefined) { if (quantity < 0 || quantity > line.stock) return res.status(400).json({ message: '数量不合法' }); await db.query('UPDATE carts SET quantity=? WHERE id=?', [quantity, line.id]); } if (selected !== undefined) await db.query('UPDATE carts SET selected=? WHERE id=?', [selected ? 1 : 0, line.id]); res.json({ message: '已更新' }); } catch (e) { next(e); } });
app.delete('/api/cart/:id', auth, async (req, res, next) => { try { const [result] = await db.query('DELETE FROM carts WHERE id=? AND user_id=?', [req.params.id, req.user.id]); if (!result.affectedRows) return res.status(404).json({ message: '购物车商品不存在' }); res.json({ message: '已删除' }); } catch (e) { next(e); } });

app.post('/api/orders', auth, async (req, res, next) => { try { const [lines] = await db.query('SELECT c.*,p.name,p.price,p.stock FROM carts c JOIN products p ON c.product_id=p.id WHERE c.user_id=? AND c.selected=1', [req.user.id]); if (!lines.length) return res.status(400).json({ message: '请选择商品后下单' }); const signature = lines.map(x => `${x.product_id}:${x.quantity}`).join('|'); const [[recent]] = await db.query("SELECT id FROM orders WHERE user_id=? AND status='PENDING' AND created_at > DATE_SUB(NOW(), INTERVAL 10 SECOND) AND order_no LIKE ?", [req.user.id, `%${signature}%`]);
    let total = 0; for (const line of lines) { if (line.stock < line.quantity) return res.status(400).json({ message: `${line.name} 库存不足` }); total += line.price * line.quantity; }
    const [created] = await db.query('INSERT INTO orders(order_no,user_id,total_amount) VALUES(?,?,?)', [orderNo() + signature, req.user.id, total]);
    for (const line of lines) { await db.query('INSERT INTO order_items(order_id,product_id,product_name,unit_price,quantity,subtotal) VALUES(?,?,?,?,?,?)', [created.insertId, line.product_id, line.name, line.price, line.quantity, line.price * line.quantity]); await db.query('UPDATE products SET stock=stock-? WHERE id=?', [line.quantity, line.product_id]); }
    await db.query('DELETE FROM carts WHERE user_id=? AND selected=1', [req.user.id]); res.status(201).json({ id: created.insertId, orderNo: orderNo(), totalAmount: total, status: 'PENDING' });
  } catch (e) { next(e); } });
app.get('/api/orders', auth, async (req, res, next) => { try { const [rows] = await db.query('SELECT id,order_no AS orderNo,user_id AS userId,total_amount AS totalAmount,status,created_at AS createdAt,paid_at AS paidAt FROM orders WHERE user_id=? ORDER BY id DESC', [req.user.id]); res.json(await Promise.all(rows.map(details))); } catch (e) { next(e); } });
app.get('/api/orders/:id', auth, async (req, res, next) => { try { const [[row]] = await db.query('SELECT id,order_no AS orderNo,user_id AS userId,total_amount AS totalAmount,status,created_at AS createdAt,paid_at AS paidAt FROM orders WHERE id=? AND user_id=?', [req.params.id, req.user.id]); if (!row) return res.status(404).json({ message: '订单不存在' }); res.json(await details(row)); } catch (e) { next(e); } });
app.post('/api/orders/:id/cancel', auth, async (req, res, next) => { const conn = await db.getConnection(); try { await conn.beginTransaction(); const [result] = await conn.query("UPDATE orders SET status='CANCELLED' WHERE id=? AND user_id=? AND status='PENDING'", [req.params.id, req.user.id]); if (result.affectedRows !== 1) { await conn.rollback(); return res.status(409).json({ message: '订单不能取消' }); } const [items] = await conn.query('SELECT * FROM order_items WHERE order_id=?', [req.params.id]); for (const item of items) await conn.query('UPDATE products SET stock=stock+? WHERE id=?', [item.quantity, item.product_id]); await conn.commit(); res.json({ message: '订单已取消' }); } catch (e) { await conn.rollback(); next(e); } finally { conn.release(); } });
app.post('/api/orders/:id/pay', auth, async (req, res, next) => { try { const [[order]] = await db.query('SELECT * FROM orders WHERE id=? AND user_id=?', [req.params.id, req.user.id]); if (!order) return res.status(404).json({ message: '订单不存在' }); if (order.status === 'PAID') return res.status(400).json({ message: '订单已支付' }); if (order.status === 'CANCELLED') return res.status(400).json({ message: '订单已取消' }); if (req.body.result === 'fail') return res.json({ message: '支付失败', status: 'PENDING' }); await db.query("UPDATE orders SET status='PAID', paid_at=NOW() WHERE id=?", [order.id]); res.json({ message: '支付成功', status: 'PAID' }); } catch (e) { next(e); } });
app.use(express.static(path.join(root, 'frontend')));
app.use((err, req, res, next) => { log('ERROR', err.message, { path: req.path, stack: err.stack }); res.status(500).json({ message: '服务器内部错误' }); });
app.listen(process.env.PORT || 3000, () => log('INFO', 'MiniMall server started', { port: process.env.PORT || 3000 }));


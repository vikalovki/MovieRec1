from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify
import sqlite3, re, os

app = Flask(__name__)
app.secret_key = "supersecretkey123"

def get_db():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    conn.create_function("lower_cyr", 1, lambda s: s.lower() if s else "")
    return conn

def is_strong_password(p):
    return len(p) >= 6 and re.search(r"\d", p) and re.search(r"[A-Za-z]", p)

def movie_with_genres(conn, where_clause="", params=(), suffix=""):
    sql = f"""
        SELECT m.*, AVG(r.rating) as avg_rating,
        (SELECT GROUP_CONCAT(name,', ') FROM (SELECT DISTINCT g2.name FROM movie_genres mg2 JOIN genres g2 ON mg2.genre_id=g2.id WHERE mg2.movie_id=m.id)) as genres
        FROM movies m LEFT JOIN ratings r ON m.id=r.movie_id
        {"WHERE " + where_clause if where_clause else ""}
        GROUP BY m.id
        {suffix}
    """
    return conn.execute(sql, params).fetchall()

# ---------- СОЗДАНИЕ ТАБЛИЦ И ЗАПОЛНЕНИЕ ЖАНРАМИ ----------
@app.before_request
def create_tables():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT
        );
        CREATE TABLE IF NOT EXISTS movies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            release_year INTEGER,
            country TEXT,
            director TEXT,
            cast TEXT,
            duration INTEGER,
            kinopoisk_rating REAL,
            poster_url TEXT,
            type TEXT DEFAULT 'movie',
            status TEXT DEFAULT 'released',
            seasons INTEGER,
            episodes INTEGER
        );
        CREATE TABLE IF NOT EXISTS genres (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS movie_genres (
            movie_id INTEGER,
            genre_id INTEGER,
            FOREIGN KEY (movie_id) REFERENCES movies(id),
            FOREIGN KEY (genre_id) REFERENCES genres(id),
            PRIMARY KEY (movie_id, genre_id)
        );
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            movie_id INTEGER,
            rating INTEGER CHECK(rating >= 1 AND rating <= 5),
            UNIQUE(user_id, movie_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (movie_id) REFERENCES movies(id)
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            movie_id INTEGER,
            review_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (movie_id) REFERENCES movies(id)
        );
        CREATE TABLE IF NOT EXISTS user_movies (
            user_id INTEGER,
            movie_id INTEGER,
            watched BOOLEAN DEFAULT 0,
            liked BOOLEAN DEFAULT 0,
            want_to_watch BOOLEAN DEFAULT 0,
            PRIMARY KEY (user_id, movie_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (movie_id) REFERENCES movies(id)
        );
        CREATE TABLE IF NOT EXISTS playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_public BOOLEAN DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS playlist_movies (
            playlist_id INTEGER,
            movie_id INTEGER,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (playlist_id, movie_id),
            FOREIGN KEY (playlist_id) REFERENCES playlists(id),
            FOREIGN KEY (movie_id) REFERENCES movies(id)
        );
        CREATE TABLE IF NOT EXISTS friends (
            user_id INTEGER,
            friend_id INTEGER,
            status TEXT DEFAULT 'pending',
            PRIMARY KEY (user_id, friend_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (friend_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS playlist_access (
            playlist_id INTEGER,
            user_id INTEGER,
            PRIMARY KEY (playlist_id, user_id),
            FOREIGN KEY (playlist_id) REFERENCES playlists(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """)
    # Заполняем жанры, если таблица пуста
    existing = conn.execute("SELECT COUNT(*) FROM genres").fetchone()[0]
    if existing == 0:
        genres = ['Боевик','Драма','Комедия','Фантастика','Ужасы','Триллер',
                  'Мелодрама','Фэнтези','Приключения','Детектив','Криминал',
                  'Исторический','Военный','Спорт','Мюзикл','Вестерн','Биография',
                  'Анимация','Семейный']
        conn.executemany("INSERT INTO genres (name) VALUES (?)", [(g,) for g in genres])
    conn.commit()
    conn.close()

# ---------- ГЛАВНАЯ ----------
@app.route("/")
def index():
    return render_template("index.html")

# ---------- ПРОФИЛИ ----------
@app.route("/profile")
def profile():
    if "user_id" not in session: return redirect("/login")
    uid = session["user_id"]
    conn = get_db()
    rated = movie_with_genres(conn, "m.id IN (SELECT movie_id FROM ratings WHERE user_id=?)", (uid,))
    fav = movie_with_genres(conn, "m.id IN (SELECT movie_id FROM user_movies WHERE user_id=? AND liked=1)", (uid,))
    want = movie_with_genres(conn, "m.id IN (SELECT movie_id FROM user_movies WHERE user_id=? AND want_to_watch=1)", (uid,))
    reviews = conn.execute("SELECT r.review_text, r.created_at, m.id, m.title FROM reviews r JOIN movies m ON r.movie_id=m.id WHERE r.user_id=? ORDER BY r.created_at DESC", (uid,)).fetchall()
    conn.close()
    return render_template("profile.html", user={"username": session["username"]}, rated_movies=rated, favorite_movies=fav, want_to_watch_movies=want, reviews=reviews, active="profile")

@app.route("/user/<int:user_id>")
def user_profile(user_id):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user: return "Пользователь не найден", 404
    rated = movie_with_genres(conn, "m.id IN (SELECT movie_id FROM ratings WHERE user_id=?)", (user_id,))
    fav = movie_with_genres(conn, "m.id IN (SELECT movie_id FROM user_movies WHERE user_id=? AND liked=1)", (user_id,))
    want = movie_with_genres(conn, "m.id IN (SELECT movie_id FROM user_movies WHERE user_id=? AND want_to_watch=1)", (user_id,))
    watched = movie_with_genres(conn, "m.id IN (SELECT movie_id FROM user_movies WHERE user_id=? AND watched=1)", (user_id,))
    reviews = conn.execute("SELECT r.review_text, r.created_at, m.id, m.title FROM reviews r JOIN movies m ON r.movie_id=m.id WHERE r.user_id=? ORDER BY r.created_at DESC", (user_id,)).fetchall()
    collections = conn.execute("""
        SELECT p.id, p.name, p.created_at, p.is_public, GROUP_CONCAT(m.poster_url) as posters
        FROM playlists p LEFT JOIN playlist_movies pm ON p.id = pm.playlist_id LEFT JOIN movies m ON pm.movie_id = m.id
        WHERE p.user_id = ? AND p.is_public = 1 GROUP BY p.id ORDER BY p.created_at DESC
    """, (user_id,)).fetchall()
    conn.close()
    return render_template("user_profile.html", user=user, rated_movies=rated, watched_movies=watched, favorite_movies=fav, want_to_watch_movies=want, reviews=reviews, collections=collections, active="friends")

# ---------- КОЛЛЕКЦИИ ----------
@app.route("/my-collections")
def my_collections():
    if "user_id" not in session: return redirect("/login")
    uid = session["user_id"]
    conn = get_db()
    own = conn.execute("""
        SELECT p.id, p.name, p.created_at, p.is_public, GROUP_CONCAT(m.poster_url) as posters
        FROM playlists p LEFT JOIN playlist_movies pm ON p.id = pm.playlist_id LEFT JOIN movies m ON pm.movie_id = m.id
        WHERE p.user_id = ? GROUP BY p.id ORDER BY p.created_at DESC
    """, (uid,)).fetchall()
    shared = conn.execute("""
        SELECT p.id, p.name, p.created_at, p.is_public, GROUP_CONCAT(m.poster_url) as posters
        FROM playlists p JOIN playlist_access pa ON p.id = pa.playlist_id
        LEFT JOIN playlist_movies pm ON p.id = pm.playlist_id LEFT JOIN movies m ON pm.movie_id = m.id
        WHERE pa.user_id = ? AND p.user_id != ? GROUP BY p.id ORDER BY p.created_at DESC
    """, (uid, uid)).fetchall()
    conn.close()
    return render_template("my_collections.html", collections=own+shared, active="collections")

@app.route("/collection/<int:collection_id>")
def view_collection(collection_id):
    if "user_id" not in session: return redirect("/login")
    uid = session["user_id"]
    if request.referrer:
        if "/my-collections" in request.referrer: session['collection_back'] = '/my-collections'
        elif "/user/" in request.referrer: session['collection_back'] = request.referrer
        elif "/collection" not in request.referrer: session.pop('collection_back', None)
    conn = get_db()
    col = conn.execute("SELECT p.*, u.username as owner_name FROM playlists p JOIN users u ON p.user_id=u.id WHERE p.id=?", (collection_id,)).fetchone()
    if not col: return "Подборка не найдена", 404
    if col["user_id"] != uid and not col["is_public"]:
        if not conn.execute("SELECT * FROM playlist_access WHERE playlist_id=? AND user_id=?", (collection_id, uid)).fetchone():
            return "Нет доступа к подборке", 403
    movies = movie_with_genres(conn, "m.id IN (SELECT movie_id FROM playlist_movies WHERE playlist_id=?)", (collection_id,))
    access_user_ids = [a["user_id"] for a in conn.execute("SELECT user_id FROM playlist_access WHERE playlist_id=?", (collection_id,)).fetchall()]
    friends = conn.execute("SELECT u.id, u.username FROM friends f JOIN users u ON f.friend_id=u.id WHERE f.user_id=? AND f.status='accepted'", (uid,)).fetchall()
    conn.close()
    return render_template("collection.html", collection=col, movies=movies, friends=friends, access_user_ids=access_user_ids, active="collections")

@app.route("/collection/create", methods=["POST"])
def create_collection():
    if "user_id" not in session: return redirect("/login")
    name = request.form.get("name","").strip()
    if not name: return redirect("/my-collections")
    conn = get_db()
    conn.execute("INSERT INTO playlists (user_id, name, is_public) VALUES (?,?,?)", (session["user_id"], name, request.form.get("is_public")=="true"))
    conn.commit(); conn.close()
    return redirect("/my-collections")

@app.route("/collection/<int:collection_id>/delete", methods=["POST"])
def delete_collection(collection_id):
    if "user_id" not in session: return redirect("/login")
    conn = get_db()
    conn.execute("DELETE FROM playlists WHERE id=? AND user_id=?", (collection_id, session["user_id"]))
    conn.commit(); conn.close()
    return redirect("/my-collections")

@app.route("/collection/<int:collection_id>/add/<int:movie_id>", methods=["POST"])
def add_to_collection(collection_id, movie_id):
    if "user_id" not in session: return jsonify({"error":"unauthorized"}),401
    conn = get_db()
    col = conn.execute("SELECT user_id FROM playlists WHERE id=?", (collection_id,)).fetchone()
    if not col: return jsonify({"error":"not found"}),404
    if col["user_id"] != session["user_id"]:
        if not conn.execute("SELECT * FROM playlist_access WHERE playlist_id=? AND user_id=?", (collection_id, session["user_id"])).fetchone():
            return jsonify({"error":"access denied"}),403
    conn.execute("INSERT OR IGNORE INTO playlist_movies (playlist_id, movie_id) VALUES (?,?)", (collection_id, movie_id))
    conn.commit(); conn.close()
    return jsonify({"success":True})

@app.route("/collection/<int:collection_id>/remove/<int:movie_id>", methods=["POST"])
def remove_from_collection(collection_id, movie_id):
    if "user_id" not in session: return redirect("/login")
    conn = get_db()
    if conn.execute("SELECT 1 FROM playlists WHERE id=? AND user_id=?", (collection_id, session["user_id"])).fetchone() or \
       conn.execute("SELECT 1 FROM playlist_access WHERE playlist_id=? AND user_id=?", (collection_id, session["user_id"])).fetchone():
        conn.execute("DELETE FROM playlist_movies WHERE playlist_id=? AND movie_id=?", (collection_id, movie_id))
        conn.commit()
    conn.close()
    return redirect(url_for("view_collection", collection_id=collection_id))

@app.route("/collection/<int:collection_id>/recommendations")
def collection_recommendations(collection_id):
    if "user_id" not in session: return redirect("/login")
    conn = get_db()
    genre_names = [g[0] for g in conn.execute("SELECT DISTINCT g.name FROM playlist_movies pm JOIN movie_genres mg ON pm.movie_id=mg.movie_id JOIN genres g ON mg.genre_id=g.id WHERE pm.playlist_id=?", (collection_id,)).fetchall()]
    if not genre_names: return "В подборке нет фильмов с жанрами", 400
    ph = ",".join(["?"]*len(genre_names))
    where_m = f"m.type='movie' AND m.id IN (SELECT DISTINCT mg2.movie_id FROM movie_genres mg2 JOIN genres g2 ON mg2.genre_id=g2.id WHERE g2.name IN ({ph})) AND m.id NOT IN (SELECT movie_id FROM playlist_movies WHERE playlist_id=?) AND m.id NOT IN (SELECT movie_id FROM user_movies WHERE user_id=? AND watched=1)"
    where_s = f"m.type='series' AND m.id IN (SELECT DISTINCT mg2.movie_id FROM movie_genres mg2 JOIN genres g2 ON mg2.genre_id=g2.id WHERE g2.name IN ({ph})) AND m.id NOT IN (SELECT movie_id FROM playlist_movies WHERE playlist_id=?) AND m.id NOT IN (SELECT movie_id FROM user_movies WHERE user_id=? AND watched=1)"
    movies = movie_with_genres(conn, where_m, genre_names + [collection_id, session["user_id"]], "ORDER BY AVG(r.rating) DESC LIMIT 10")
    series = movie_with_genres(conn, where_s, genre_names + [collection_id, session["user_id"]], "ORDER BY AVG(r.rating) DESC LIMIT 10")
    conn.close()
    return render_template("collection_recommendations.html", movies=movies, series=series, col_id=collection_id, active="collections")

@app.route("/collection/<int:collection_id>/share", methods=["POST"])
def share_collection(collection_id):
    if "user_id" not in session: return redirect("/login")
    username = request.form.get("username","").strip()
    if not username: return redirect(url_for("view_collection", collection_id=collection_id))
    conn = get_db()
    friend = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if not friend: flash("Пользователь не найден", "error"); return redirect(url_for("view_collection", collection_id=collection_id))
    if not conn.execute("SELECT * FROM friends WHERE user_id=? AND friend_id=? AND status='accepted'", (session["user_id"], friend["id"])).fetchone():
        flash("Пользователь не в друзьях", "error"); return redirect(url_for("view_collection", collection_id=collection_id))
    conn.execute("INSERT OR IGNORE INTO playlist_access (playlist_id, user_id) VALUES (?,?)", (collection_id, friend["id"]))
    conn.commit(); conn.close()
    flash("Доступ предоставлен", "success")
    return redirect(url_for("view_collection", collection_id=collection_id))

# ---------- ДРУЗЬЯ ----------
@app.route("/friends")
def friends():
    if "user_id" not in session: return redirect("/login")
    uid = session["user_id"]
    conn = get_db()
    flist = conn.execute("SELECT u.id, u.username FROM friends f JOIN users u ON f.friend_id=u.id WHERE f.user_id=? AND f.status='accepted'", (uid,)).fetchall()
    reqs = conn.execute("SELECT u.id, u.username FROM friends f JOIN users u ON f.user_id=u.id WHERE f.friend_id=? AND f.status='pending'", (uid,)).fetchall()
    conn.close()
    return render_template("friends.html", friends=flist, requests=reqs, active="friends")

@app.route("/friends/add", methods=["POST"])
def add_friend():
    if "user_id" not in session: return redirect("/login")
    username = request.form.get("username","").strip()
    if not username: return redirect("/friends")
    conn = get_db()
    friend = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if not friend: flash("Пользователь не найден", "error"); return redirect("/friends")
    if friend["id"] == session["user_id"]: flash("Нельзя добавить самого себя", "error"); return redirect("/friends")
    if conn.execute("SELECT * FROM friends WHERE (user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)", (session["user_id"], friend["id"], friend["id"], session["user_id"])).fetchone():
        flash("Заявка уже отправлена или вы друзья", "error"); return redirect("/friends")
    conn.execute("INSERT INTO friends (user_id, friend_id, status) VALUES (?,?, 'pending')", (session["user_id"], friend["id"]))
    conn.commit(); conn.close()
    flash("Запрос отправлен", "success")
    return redirect("/friends")

@app.route("/friends/accept/<int:friend_id>", methods=["POST"])
def accept_friend(friend_id):
    if "user_id" not in session: return redirect("/login")
    conn = get_db()
    conn.execute("UPDATE friends SET status='accepted' WHERE user_id=? AND friend_id=?", (friend_id, session["user_id"]))
    conn.execute("INSERT OR IGNORE INTO friends (user_id, friend_id, status) VALUES (?,?, 'accepted')", (session["user_id"], friend_id))
    conn.commit(); conn.close()
    flash("Заявка принята", "success")
    return redirect("/friends")

@app.route("/friends/remove/<int:friend_id>", methods=["POST"])
def remove_friend(friend_id):
    if "user_id" not in session: return redirect("/login")
    conn = get_db()
    conn.execute("DELETE FROM friends WHERE (user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)", (session["user_id"], friend_id, friend_id, session["user_id"]))
    conn.commit(); conn.close()
    return redirect("/friends")

# ---------- КАТАЛОГ ----------
@app.route("/home")
def home():
    if "user_id" not in session: return redirect("/login")
    q = request.args.get("q","").strip()
    genre = request.args.get("genre","").strip()
    is_search = bool(q or genre)
    conn = get_db()
    base = """SELECT m.*, AVG(r.rating) as avg_rating,
              (SELECT GROUP_CONCAT(name,', ') FROM (SELECT DISTINCT g2.name FROM movie_genres mg2 JOIN genres g2 ON mg2.genre_id=g2.id WHERE mg2.movie_id=m.id)) as genres
              FROM movies m LEFT JOIN ratings r ON m.id=r.movie_id"""
    cond = []
    params = []
    if q:
        cond.append("(lower_cyr(m.title) LIKE lower_cyr(?) OR lower_cyr(m.description) LIKE lower_cyr(?) OR lower_cyr(m.director) LIKE lower_cyr(?) OR lower_cyr(m.cast) LIKE lower_cyr(?) OR EXISTS (SELECT 1 FROM movie_genres mg2 JOIN genres g2 ON mg2.genre_id=g2.id WHERE mg2.movie_id=m.id AND lower_cyr(g2.name) LIKE lower_cyr(?)))")
        params.extend([f"%{q}%"]*5)
    if genre:
        cond.append("EXISTS (SELECT 1 FROM movie_genres mg2 JOIN genres g2 ON mg2.genre_id=g2.id WHERE mg2.movie_id=m.id AND lower_cyr(g2.name)=lower_cyr(?))")
        params.append(genre)
    if cond: base += " WHERE " + " AND ".join(cond)
    base += " GROUP BY m.id ORDER BY m.title"
    movies = conn.execute(base, params).fetchall()
    new_movies = [] if is_search else conn.execute("""SELECT m.id, m.title, m.release_year, m.poster_url, m.type, AVG(r.rating) as avg_rating,
        (SELECT GROUP_CONCAT(name,', ') FROM (SELECT DISTINCT g2.name FROM movie_genres mg2 JOIN genres g2 ON mg2.genre_id=g2.id WHERE mg2.movie_id=m.id)) as genres
        FROM movies m LEFT JOIN ratings r ON m.id=r.movie_id WHERE m.release_year>=2024 GROUP BY m.id ORDER BY m.release_year DESC LIMIT 6""").fetchall()
    all_genres = [row["name"] for row in conn.execute("SELECT name FROM genres ORDER BY name").fetchall()]
    conn.close()
    return render_template("home.html", movies=movies, new_movies=new_movies, search_query=q, genre_filter=genre, all_genres=all_genres, is_search=is_search, active="home")

# ---------- РЕГИСТРАЦИЯ / ВХОД ----------
@app.route("/register", methods=["GET","POST"])
def register():
    if request.method=="POST":
        u = request.form["username"].strip()
        p = request.form["password"]
        email = request.form.get("email", "").strip()
        if not email or not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            flash("Введите корректный email (должен содержать @ и точку)", "error")
            return render_template("register.html", email=email)
        if not is_strong_password(p):
            flash("Пароль слишком слабый (минимум 6 символов, буквы + цифры)", "error")
            return render_template("register.html", email=email)
        conn = get_db()
        if conn.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone():
            conn.close()
            flash("Пользователь с таким именем уже существует", "error")
            return render_template("register.html", email=email)
        conn.execute("INSERT INTO users (username,password,email) VALUES (?,?,?)", (u,p,email))
        conn.commit(); conn.close()
        flash("Регистрация успешна! Теперь войдите.", "success")
        return redirect("/login")
    return render_template("register.html", email="")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        login_input = request.form["username"].strip()
        p = request.form["password"]
        conn = get_db()
        if "@" in login_input:
            user = conn.execute("SELECT * FROM users WHERE email=? AND password=?", (login_input, p)).fetchone()
        else:
            user = conn.execute("SELECT * FROM users WHERE username=? AND password=?", (login_input, p)).fetchone()
        conn.close()
        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect("/recommendations")
        else:
            flash("Неверный логин/email или пароль", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ---------- ДЕТАЛИ ФИЛЬМА, ОЦЕНКИ, СТАТУСЫ ----------
@app.route("/rate/<int:movie_id>", methods=["POST"])
def rate(movie_id):
    if "user_id" not in session: return redirect("/login")
    r = int(request.form.get("rating",0))
    if r<1 or r>5: return redirect(url_for("movie_detail", movie_id=movie_id))
    uid = session["user_id"]
    conn = get_db()
    conn.execute("INSERT INTO ratings (user_id,movie_id,rating) VALUES (?,?,?) ON CONFLICT(user_id,movie_id) DO UPDATE SET rating=?", (uid,movie_id,r,r))
    conn.execute("INSERT INTO user_movies (user_id,movie_id,watched) VALUES (?,?,1) ON CONFLICT(user_id,movie_id) DO UPDATE SET watched=1", (uid,movie_id))
    conn.commit(); conn.close()
    return redirect(url_for("movie_detail", movie_id=movie_id))

@app.route("/mark_watched/<int:movie_id>", methods=["POST"])
@app.route("/mark_liked/<int:movie_id>", methods=["POST"])
@app.route("/mark_want_to_watch/<int:movie_id>", methods=["POST"])
def mark_status(movie_id):
    if "user_id" not in session: return jsonify({"error":"unauthorized"}),401
    uid = session["user_id"]
    field = request.path.split("/")[1].replace("mark_","")
    val = request.form.get(field)=="true"
    conn = get_db()
    if field == "liked":
        if val:
            conn.execute(
                "INSERT INTO user_movies (user_id, movie_id, watched, liked) VALUES (?, ?, 1, 1) "
                "ON CONFLICT(user_id, movie_id) DO UPDATE SET liked = 1, watched = 1",
                (uid, movie_id)
            )
        else:
            conn.execute(
                "INSERT INTO user_movies (user_id, movie_id, watched, liked) VALUES (?, ?, 0, 0) "
                "ON CONFLICT(user_id, movie_id) DO UPDATE SET liked = 0",
                (uid, movie_id)
            )
    elif field == "watched":
        conn.execute(
            "INSERT INTO user_movies (user_id, movie_id, watched) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, movie_id) DO UPDATE SET watched = ?",
            (uid, movie_id, val, val)
        )
    elif field == "want_to_watch":
        conn.execute(
            "INSERT INTO user_movies (user_id, movie_id, want_to_watch) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, movie_id) DO UPDATE SET want_to_watch = ?",
            (uid, movie_id, val, val)
        )
    conn.commit()
    conn.close()
    return jsonify({"success":True})

@app.route("/movie/<int:movie_id>", methods=["GET","POST"])
def movie_detail(movie_id):
    if request.referrer and ("/profile" in request.referrer or "/recommendations" in request.referrer or "/home" in request.referrer or "/collection" in request.referrer):
        session['previous_page'] = request.referrer
    conn = get_db()
    movie = conn.execute("""SELECT m.*, AVG(r.rating) as avg_rating,
        (SELECT GROUP_CONCAT(name,', ') FROM (SELECT DISTINCT g2.name FROM movie_genres mg2 JOIN genres g2 ON mg2.genre_id=g2.id WHERE mg2.movie_id=m.id)) as genres
        FROM movies m LEFT JOIN ratings r ON m.id=r.movie_id WHERE m.id=? GROUP BY m.id""", (movie_id,)).fetchone()
    if not movie: return "Фильм не найден", 404
    user_rating, user_collections = None, []
    if "user_id" in session:
        uid = session["user_id"]
        rr = conn.execute("SELECT rating FROM ratings WHERE user_id=? AND movie_id=?", (uid,movie_id)).fetchone()
        if rr: user_rating = rr["rating"]
        user_collections = conn.execute("SELECT id, name FROM playlists WHERE user_id=? UNION SELECT p.id, p.name FROM playlists p JOIN playlist_access pa ON p.id=pa.playlist_id WHERE pa.user_id=? AND p.user_id!=? ORDER BY name", (uid,uid,uid)).fetchall()
    reviews = conn.execute("SELECT r.review_text, r.created_at, u.username FROM reviews r JOIN users u ON r.user_id=u.id WHERE r.movie_id=? ORDER BY r.created_at DESC", (movie_id,)).fetchall()
    status = {"watched":False,"liked":False,"want_to_watch":False}
    if "user_id" in session:
        s = conn.execute("SELECT watched,liked,want_to_watch FROM user_movies WHERE user_id=? AND movie_id=?", (session["user_id"],movie_id)).fetchone()
        if s: status = {k:bool(v) for k,v in zip(["watched","liked","want_to_watch"], s)}
    if request.method=="POST":
        txt = request.form.get("review_text","").strip()
        if txt:
            conn.execute("INSERT INTO reviews (user_id,movie_id,review_text) VALUES (?,?,?)", (session["user_id"],movie_id,txt))
            conn.commit(); conn.close()
            return redirect(url_for("movie_detail", movie_id=movie_id))
    conn.close()
    return render_template("movie_detail.html", movie=movie, reviews=reviews, user_status=status, user_rating=user_rating, user_collections=user_collections)

# ---------- РЕКОМЕНДАЦИИ ----------
@app.route("/recommendations")
def recommendations():
    if "user_id" not in session: return redirect("/login")
    uid = session["user_id"]
    conn = get_db()
    rated_cnt = conn.execute("SELECT COUNT(*) FROM ratings WHERE user_id=?", (uid,)).fetchone()[0]
    if rated_cnt < 5:
        conn.close()
        return render_template("recommendations.html", movies=[], series=[], is_new_user=True, rated_count=rated_cnt, active="recommendations")
    liked_genres = [g[0] for g in conn.execute("SELECT DISTINCT g.name FROM user_movies um JOIN movie_genres mg ON um.movie_id=mg.movie_id JOIN genres g ON mg.genre_id=g.id WHERE um.user_id=? AND um.liked=1", (uid,)).fetchall()]
    if not liked_genres:
        movies = movie_with_genres(conn, "m.type='movie' AND m.id NOT IN (SELECT movie_id FROM user_movies WHERE user_id=? AND watched=1)", (uid,), "ORDER BY AVG(r.rating) DESC LIMIT 10")
        series = movie_with_genres(conn, "m.type='series' AND m.id NOT IN (SELECT movie_id FROM user_movies WHERE user_id=? AND watched=1)", (uid,), "ORDER BY AVG(r.rating) DESC LIMIT 10")
    else:
        ph = ",".join(["?"]*len(liked_genres))
        where_m = f"m.type='movie' AND m.id IN (SELECT DISTINCT mg2.movie_id FROM movie_genres mg2 JOIN genres g2 ON mg2.genre_id=g2.id WHERE g2.name IN ({ph})) AND m.id NOT IN (SELECT movie_id FROM user_movies WHERE user_id=? AND watched=1)"
        where_s = f"m.type='series' AND m.id IN (SELECT DISTINCT mg2.movie_id FROM movie_genres mg2 JOIN genres g2 ON mg2.genre_id=g2.id WHERE g2.name IN ({ph})) AND m.id NOT IN (SELECT movie_id FROM user_movies WHERE user_id=? AND watched=1)"
        movies = movie_with_genres(conn, where_m, liked_genres+[uid], "ORDER BY AVG(r.rating) DESC LIMIT 12")
        series = movie_with_genres(conn, where_s, liked_genres+[uid], "ORDER BY AVG(r.rating) DESC LIMIT 12")
    conn.close()
    return render_template("recommendations.html", movies=movies, series=series, is_new_user=False, rated_count=rated_cnt, active="recommendations")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

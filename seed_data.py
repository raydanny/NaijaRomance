"""
seed_data.py — Populate NaijaRomance with realistic demo users.
Run once:  python seed_data.py
Re-seed:   python seed_data.py --force
"""
import os, sys, random
from datetime import datetime, date, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from app import app, db, User, Profile, Like, Message, Wink, Notification, ProfileView
from app import NIGERIAN_STATES, ETHNICITIES, RELIGIONS, EDUCATION, BODY_TYPES, RELATIONSHIP_GOALS
from app import NOTIF_LIKE, NOTIF_MESSAGE, NOTIF_VIEW, NOTIF_MATCH

# ── Name pools ────────────────────────────────────────────────────────────────
MALE_NAMES = [
    'Chukwuemeka','Tunde','Emeka','Segun','Kola','Biodun','Ibrahim','Musa',
    'Chidi','Femi','Rotimi','Lanre','Uche','Ahmed','Suleiman','Yakubu',
    'Damilola','Babatunde','Gbenga','Olawale','Nnamdi','Chisom','Obinna',
    'Ifeanyi','Bola','Kayode','Adebayo','Hassan','Garba','Aliyu','Jide',
    'Damola','Tochukwu','Kenechukwu','Tokunbo','Kunle','Deji','Wale',
]
FEMALE_NAMES = [
    'Ngozi','Amaka','Funmi','Yetunde','Aisha','Fatima','Chidinma',
    'Adaeze','Blessing','Grace','Nneka','Bukola','Kemi','Toyin','Sade',
    'Halima','Zainab','Rukayat','Chiamaka','Ifeoma','Ebere','Uchechi',
    'Oluwaseun','Adaora','Temitope','Folake','Mariam','Hauwa','Jumoke','Lola',
    'Chinwe','Onyinye','Chioma','Obiageli','Nkechi','Adeola','Ronke',
]
LAST_NAMES = [
    'Okafor','Adeyemi','Musa','Ibrahim','Eze','Okonkwo','Bello','Adesanya',
    'Nwosu','Lawal','Okeke','Adeleke','Yusuf','Abdullahi','Ogbu','Obi',
    'Nwachukwu','Afolabi','Sani','Usman','Inyang','Effiong','Chukwu',
    'Taiwo','Fashola','Alabi','Ogundimu','Banjo','Dada','Ogundipe',
]
OCCUPATIONS = [
    'Software Engineer','Doctor','Nurse','Teacher','Banker','Trader','Lawyer',
    'Accountant','Entrepreneur','Civil Servant','Pharmacist','Architect',
    'Journalist','Fashion Designer','Chef','Electrician','Mechanical Engineer',
    'HR Manager','Marketing Executive','Graphic Designer','Data Analyst',
    'Nurse Practitioner','Business Owner','Sales Representative','Pastor',
]
CITIES = {
    'Lagos':       ['Ikeja','Lekki','Surulere','Yaba','Ikorodu','Ajah','Badagry'],
    'FCT - Abuja': ['Garki','Wuse','Maitama','Gwarinpa','Kubwa','Lugbe'],
    'Rivers':      ['Port Harcourt','Obio-Akpor','Eleme','Bonny','Okrika'],
    'Kano':        ['Kano Municipal','Fagge','Dala','Gwale','Tarauni'],
    'Oyo':         ['Ibadan North','Ibadan South','Ogbomoso','Oyo East'],
    'Delta':       ['Warri','Asaba','Uvwie','Sapele','Ughelli'],
    'Enugu':       ['Enugu North','Enugu South','Udi','Igbo-Eze','Nkanu'],
    'Imo':         ['Owerri','Orlu','Okigwe','Ikeduru','Mbaitoli'],
    'Edo':         ['Benin City','Ikpoba-Okha','Oredo','Egor','Ovia'],
    'Anambra':     ['Onitsha','Awka','Nnewi','Ogidi','Ekwulobia'],
}
INTERESTS_POOL = [
    'Music','Football','Cooking','Travel','Reading','Movies','Dancing',
    'Photography','Fashion','Fitness','Tech','Agriculture','Art','Gaming',
    'Gospel','Prayer','Politics','Business','Poetry','Volleyball','Tennis',
    'Hiking','Swimming','Baking','Food','Cars','Comedy','Nollywood',
    'Afrobeats','Jazz','Entrepreneurship','Investments','Nature',
]
ABOUT_TEMPLATES = [
    "I am a simple, easy-going person who loves life to the fullest. I enjoy spending quality time with family and close friends. Looking for someone genuine who means what they say.",
    "God-fearing, hardworking and fun to be with. I love to laugh and create memories. Ready to build something serious with the right person.",
    "I believe love is the greatest gift one can give. I am caring, loyal and brutally honest. Looking for my forever person — no games, no pretence.",
    "Life is short so I choose to enjoy every moment. I enjoy good food, great music and deep conversations. Let us vibe!",
    "I am a focused individual who knows exactly what I want. Looking for a serious, committed partner who is ready to grow together.",
    "Kind-hearted and highly ambitious. I value honesty and loyalty above everything else. If you are genuine, let us talk.",
    "I love exploring new places and experiencing Nigerian culture across all its diversity. Would love a partner to share these adventures with.",
    "Family means everything to me. Traditional at heart but modern in thinking. Ready to build a home with the right person.",
    "Passionate about my career and equally passionate about love. I am looking for someone who matches my energy and drive.",
    "I am outgoing, sociable and always smiling. Looking for a genuine connection that grows naturally into something beautiful.",
    "I enjoy the simple things — a good meal, a long walk, quality time with people I care about. Looking for real love, not performance.",
    "Born and raised in Nigeria, proud of my roots and culture. I am ready to settle down with someone who shares my values.",
    "I work hard and play harder. Looking for a partner who can keep up and push me to be better every day.",
    "Quiet when you first meet me, but you will never stop laughing once you get to know me. Looking for that special one.",
    "I am a giver — I give my time, attention and love fully. Looking for someone who can match that same energy.",
]


def random_dob(min_age=21, max_age=46):
    today = date.today()
    age   = random.randint(min_age, max_age)
    doy   = random.randint(0, 364)
    try:
        return date(today.year - age, 1, 1) + timedelta(days=doy)
    except ValueError:
        return date(today.year - age, 6, 15)


def seed(force=False, wipe=False):
    with app.app_context():
        db.create_all()

        if wipe:
            print("Wiping existing demo users (email ends in @demo.nr)…")
            demo_users = User.query.filter(User.email.like('%@demo.nr')).all()
            for u in demo_users:
                db.session.delete(u)
            db.session.commit()
            print(f"  Removed {len(demo_users)} demo users.")

        existing = User.query.count()
        if existing >= 40 and not force and not wipe:
            print(f"Already have {existing} users — use --force to re-seed or --wipe to clean first.")
            return

        print("Seeding demo users…")
        users_created = []

        target_count = 80
        attempts     = 0

        while len(users_created) < target_count and attempts < target_count * 3:
            attempts += 1
            gender = random.choice(['Male', 'Female'])
            fname  = random.choice(MALE_NAMES if gender == 'Male' else FEMALE_NAMES)
            lname  = random.choice(LAST_NAMES)
            state  = random.choice(NIGERIAN_STATES)

            uname = (fname + lname[:3]).lower() + str(random.randint(10, 999))
            uname = ''.join(c for c in uname if c.isalnum() or c == '_')
            if User.query.filter_by(username=uname).first():
                continue

            email = f"{uname}@demo.nr"
            if User.query.filter_by(email=email).first():
                continue

            # Spread last_seen: 20% online now, 30% last hour, rest up to 14 days ago
            r = random.random()
            if r < 0.20:
                last_seen = datetime.utcnow() - timedelta(minutes=random.randint(0, 4))
            elif r < 0.50:
                last_seen = datetime.utcnow() - timedelta(minutes=random.randint(5, 60))
            else:
                last_seen = datetime.utcnow() - timedelta(hours=random.randint(1, 336))

            user = User(username=uname, email=email, last_seen=last_seen)
            user.set_password('demo1234')
            db.session.add(user)
            db.session.flush()

            city_options = CITIES.get(state, [state + ' Central'])
            city         = random.choice(city_options)

            interests_sample = random.sample(INTERESTS_POOL, random.randint(4, 8))
            seeking = 'Female' if gender == 'Male' else 'Male'
            if random.random() < 0.04:
                seeking = 'Both'

            profile = Profile(
                user_id          = user.id,
                first_name       = fname,
                last_name        = lname,
                gender           = gender,
                seeking          = seeking,
                date_of_birth    = random_dob(),
                state            = state,
                city             = city,
                ethnicity        = random.choice(ETHNICITIES),
                religion         = random.choice(RELIGIONS),
                education        = random.choice(EDUCATION),
                occupation       = random.choice(OCCUPATIONS),
                body_type        = random.choice(BODY_TYPES),
                height_cm        = random.randint(155, 193),
                relationship_goal= random.choice(RELATIONSHIP_GOALS),
                about_me         = random.choice(ABOUT_TEMPLATES),
                interests        = ', '.join(interests_sample),
                profile_complete = True,
            )
            db.session.add(profile)
            users_created.append(user)

        db.session.commit()
        print(f"  Created {len(users_created)} users.")

        # ── Likes ──────────────────────────────────────────────────────────────
        print("  Adding likes…")
        for u in users_created:
            n_likes = random.randint(2, 10)
            targets = random.sample([x for x in users_created if x.id != u.id],
                                    min(n_likes, len(users_created) - 1))
            for t in targets:
                from sqlalchemy.exc import IntegrityError
                try:
                    db.session.add(Like(
                        liker_id   = u.id,
                        liked_id   = t.id,
                        created_at = datetime.utcnow() - timedelta(hours=random.randint(0, 240))
                    ))
                    db.session.flush()
                except IntegrityError:
                    db.session.rollback()
        db.session.commit()

        # ── Messages ───────────────────────────────────────────────────────────
        print("  Adding messages…")
        openers = [
            "Hello! I came across your profile and found it really interesting. How are you?",
            "Hi {name}! Hope you are having a great day. I think we have a lot in common!",
            "Good day! I saw you are from {state} — I have family there. Let us chat!",
            "Hey! Your profile caught my eye. Would love to get to know you better.",
            "Hello! I enjoy {interest} too! We already have something to talk about 😊",
            "Hi there! Simple and straightforward — I like what I see. Let us connect.",
            "Greetings! Your smile in the photo is contagious. Hope to chat with you!",
        ]
        replies = [
            "Thank you for reaching out! I appreciate your kind words.",
            "Hello! Nice to hear from you. How are you doing?",
            "Hi! Yes, let us definitely chat more. Tell me about yourself.",
            "Thanks! I checked your profile too and I love what I see.",
            "Hi! I am doing well, thank you. Hope you are too!",
        ]

        pairs = set()
        for _ in range(60):
            a, b = random.sample(users_created, 2)
            key  = (min(a.id, b.id), max(a.id, b.id))
            if key in pairs:
                continue
            pairs.add(key)

            opener = random.choice(openers)
            opener = opener.replace('{name}', b.profile.first_name if b.profile else b.username)
            opener = opener.replace('{state}', a.profile.state if a.profile else 'Lagos')
            if '{interest}' in opener:
                interests = a.profile.interests_list() if a.profile else ['Music']
                opener = opener.replace('{interest}', random.choice(interests) if interests else 'Music')

            t_sent = datetime.utcnow() - timedelta(hours=random.randint(0, 72))
            db.session.add(Message(
                sender_id=a.id, receiver_id=b.id, body=opener,
                sent_at=t_sent, is_read=random.random() > 0.4
            ))

            # 60% chance of a reply
            if random.random() < 0.6:
                db.session.add(Message(
                    sender_id=b.id, receiver_id=a.id,
                    body=random.choice(replies),
                    sent_at=t_sent + timedelta(minutes=random.randint(2, 120)),
                    is_read=True
                ))
        db.session.commit()

        # ── Winks ──────────────────────────────────────────────────────────────
        print("  Adding winks…")
        for _ in range(30):
            a, b = random.sample(users_created, 2)
            from sqlalchemy.exc import IntegrityError
            try:
                db.session.add(Wink(
                    sender_id   = a.id,
                    receiver_id = b.id,
                    created_at  = datetime.utcnow() - timedelta(hours=random.randint(0, 48)),
                    is_seen     = random.random() > 0.5
                ))
                db.session.flush()
            except IntegrityError:
                db.session.rollback()
        db.session.commit()

        # ── Profile Views ──────────────────────────────────────────────────────
        print("  Adding profile views…")
        for _ in range(120):
            a, b = random.sample(users_created, 2)
            db.session.add(ProfileView(
                viewer_id=a.id,
                viewed_id=b.id,
                viewed_at=datetime.utcnow() - timedelta(hours=random.randint(0, 168))
            ))
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

        # ── Notifications ──────────────────────────────────────────────────────
        print("  Adding notifications…")
        notif_types = [NOTIF_LIKE, NOTIF_MESSAGE, NOTIF_VIEW, NOTIF_MATCH, 'wink']
        for _ in range(80):
            a, b = random.sample(users_created, 2)
            ntype = random.choice(notif_types)
            db.session.add(Notification(
                recipient_id=b.id,
                actor_id=a.id,
                notif_type=ntype,
                is_read=random.random() > 0.4,
                created_at=datetime.utcnow() - timedelta(hours=random.randint(0, 72))
            ))
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

        total = User.query.count()
        print(f"\n✅ Seed complete!")
        print(f"   Total users in DB: {total}")
        print(f"   All demo passwords: demo1234")
        print(f"   Example login: {users_created[0].username} / demo1234")


if __name__ == '__main__':
    force = '--force' in sys.argv
    wipe  = '--wipe'  in sys.argv
    seed(force=force, wipe=wipe)

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship


Base = declarative_base()


class Users(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)  # Telegram user ID
    access_level = Column(Integer, default=0)  # 0 - no access, 1 - view, 2 - save and view
    current_password = Column(String, nullable=True)
    selected_court_id = Column(Integer, ForeignKey('courts.id'), nullable=True)
    court = relationship('Courts', back_populates='users', lazy="selectin")
    videos = relationship('Videos', back_populates='user', lazy="selectin")


class Videos(Base):
    __tablename__ = 'videos'
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String, nullable=False)  # Telegram file ID
    description = Column(String, nullable=True)
    timestamp = Column(DateTime, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    court_id = Column(Integer, ForeignKey('courts.id'), nullable=False)
    public = Column(Boolean, nullable=False, default=False)

    user = relationship('Users', back_populates='videos', lazy="selectin")
    court = relationship('Courts', back_populates='videos', lazy="selectin")


class Courts(Base):
    __tablename__ = 'courts'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    totp_secret = Column(String, nullable=True)

    users = relationship('Users', back_populates='court', lazy="selectin")
    videos = relationship('Videos', back_populates='court', lazy="selectin")
    cameras = relationship('Cameras', back_populates='court', lazy="selectin")


class Cameras(Base):
    __tablename__ = 'cameras'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    login = Column(String, nullable=False)
    password = Column(String, nullable=False)
    ip = Column(String, nullable=False)
    port = Column(Integer, nullable=False)
    court_id = Column(Integer, ForeignKey('courts.id'), nullable=False)
    court = relationship('Courts', back_populates='cameras', lazy="selectin")


TABLES = {
    'users': Users,
    'videos': Videos,
    'courts': Courts,
    'cameras': Cameras
}
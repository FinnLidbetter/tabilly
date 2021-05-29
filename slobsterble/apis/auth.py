"""Handler for user authentication."""

import flask_login
from flask import (
    Response,
    flash,
    redirect,
    render_template,
    request,
    url_for,
    jsonify,
)
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_jwt_identity,
    jwt_required,
)
from flask_restful import Resource
from werkzeug.security import generate_password_hash

from slobsterble.app import db
from slobsterble.models import (
    BoardLayout,
    Dictionary,
    Distribution,
    Player,
    User,
)
from slobsterble.forms import LoginForm, RegisterForm


class TokenRefreshView(Resource):

    @staticmethod
    @jwt_required(refresh=True)
    def post():
        identity = get_jwt_identity()
        access_token = create_access_token(identity=identity, fresh=False)
        return jsonify(access_token=access_token)


class LoginView(Resource):

    @staticmethod
    def post():
        username = request.json.get("username", None)
        password = request.json.get("password", None)

        user = User.query.filter_by(username=username).one_or_none()
        if not user or not user.check_password(password):
            return Response('Incorrect username or password', status=401)

        access_token = create_access_token(identity=user, fresh=True)
        refresh_token = create_refresh_token(identity=user)
        return jsonify(access_token=access_token, refresh_token=refresh_token)


class AdminLoginView(Resource):

    @staticmethod
    def get():
        form = LoginForm()
        return Response(render_template(
            'auth/admin-login.html', title='Sign In', form=form), status=200)

    @staticmethod
    def post():
        form = LoginForm()
        if form.validate_on_submit():
            user = User.query.filter_by(username=form.username.data).first()
            if user is None or not user.check_password(form.password.data):
                flash('Invalid username or password')
                return redirect(url_for('auth.admin_login'))
            response = redirect(url_for('admin.index'))
            flask_login.login_user(user)
            return response
        return Response(
            render_template('auth/admin-login.html', title='Sign In',
                            form=form), status=200)


class AdminLogoutView(Resource):

    @staticmethod
    def get():
        flask_login.logout_user()
        return redirect(url_for('adminloginview'))


class WebsiteRegisterView(Resource):

    @staticmethod
    def get():
        form = RegisterForm()
        return Response(render_template('auth/register.html', title='Register', form=form), status=200)

    @staticmethod
    def post():
        form = RegisterForm()
        if form.validate_on_submit():
            existing_user = User.query.filter_by(
                username=form.username.data).first()
            if existing_user:
                flash('User with this username already exists.')
                return Response(
                    render_template('auth/register.html', title='Register',
                                    form=form), status=200)
            if form.password.data != form.confirm_password.data:
                flash('Passwords do not match.')
                return Response(
                    render_template('auth/register.html', title='Register',
                                    form=form), status=200)
            new_user = User(username=form.username.data,
                            password_hash=generate_password_hash(form.password.data))
            db.session.add(new_user)
            default_dictionary = db.session.query(Dictionary).filter_by(
                id=2).first()
            default_board_layout = db.session.query(BoardLayout).filter_by(
                name='Classic').first()
            default_distribution = db.session.query(Distribution).filter_by(
                name='Classic').first()
            new_player = Player(user=new_user, display_name=form.display_name.data,
                                dictionary=default_dictionary,
                                board_layout=default_board_layout,
                                distribution=default_distribution)
            db.session.add(new_player)
            db.session.commit()
            return redirect(url_for('indexview'))
        flash('Invalid form submission')
        return Response(render_template('auth/register.html', title='Register', form=form), status=200)


class RegisterView(Resource):

    @staticmethod
    def post():
        data = request.get_json()
        expected_fields = ['username', 'password',
                           'confirmed_password', 'display_name']
        if not all([field in data for field in expected_fields]):
            return Response('Bad request', status=401,
                            mimetype='application/json')
        existing_user = User.query.filter_by(username=data['username']).first()
        if existing_user:
            return Response('User with this username already exists.', status=400)
        if data['password'] != data['confirmed_password']:
            return Response('Passwords do not match.', status=400)
        new_user = User(username=data['username'],
                        password_hash=generate_password_hash(data['password']))
        db.session.add(new_user)
        default_dictionary = db.session.query(Dictionary).filter_by(id=2).first()
        default_board_layout = db.session.query(BoardLayout).filter_by(
            name='Classic').first()
        default_distribution = db.session.query(Distribution).filter_by(
            name='Classic').first()
        if default_dictionary is None:
            return Response('Internal server error.', status=400)
        new_player = Player(user=new_user, display_name=data['display_name'],
                            dictionary=default_dictionary,
                            board_layout=default_board_layout,
                            distribution=default_distribution)
        db.session.add(new_player)
        db.session.commit()
        return Response('Success!', status=200)

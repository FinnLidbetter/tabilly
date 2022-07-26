"""Handler for user authentication."""

import datetime
import re
import time
import urllib.parse
from secrets import token_urlsafe
from smtplib import SMTPException

import flask_login
from flask import (
    Response,
    current_app,
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
    current_user,
    decode_token,
    jwt_required,
    get_jwt,
)
from flask_jwt_extended.config import config as jwt_config
from flask_restful import Resource
from werkzeug.datastructures import MultiDict
from werkzeug.security import check_password_hash, generate_password_hash

from slobsterble.app import db, mail
from slobsterble.constants import (
    PASSWORD_RESET_VERIFICATION_SECONDS,
    REGISTRATION_VERIFICATION_SECONDS,
)
from slobsterble.models import (
    BoardLayout,
    Device,
    Dictionary,
    Distribution,
    Player,
    User,
    UserVerification,
)
from slobsterble.forms import LoginForm, PasswordResetForm, RegisterForm


class TokenRefreshView(Resource):

    @staticmethod
    @jwt_required(refresh=True)
    def post():
        """Get a new access token if the refresh token is still valid."""
        jwt = get_jwt()
        refresh_token_iat = jwt.get('iat', 0)
        if current_user.refresh_token_iat != refresh_token_iat:
            # The refresh token has been invalidated by a user logout.
            return Response(status=401)
        access_token = create_access_token(identity=current_user, fresh=False)
        access_expiration_timestamp = \
            decode_token(access_token).get('iat') + jwt_config.access_expires.seconds
        data = {
            'token': access_token,
            'expiration_date': access_expiration_timestamp
        }
        return jsonify(data)


class LoginView(Resource):

    @staticmethod
    def post():
        username = request.json.get("username", None)
        password = request.json.get("password", None)
        device_token = request.json.get("deviceToken", None)

        user = User.query.filter_by(username=username).one_or_none()
        if not user or not user.check_password(password):
            return Response('Incorrect username or password', status=401)

        now = datetime.datetime.now(datetime.timezone.utc)
        access_token = create_access_token(identity=user, fresh=True)
        access_expiration_date = now + jwt_config.access_expires
        refresh_token = create_refresh_token(identity=user)
        refresh_iat = decode_token(refresh_token).get('iat', 0)
        user.refresh_token_iat = refresh_iat
        refresh_expiration_date = now + jwt_config.refresh_expires
        data = {
            'access_token': {
                'token': access_token,
                'expiration_date': access_expiration_date.timestamp(),
            },
            'refresh_token': {
                'token': refresh_token,
                'expiration_date': refresh_expiration_date.timestamp(),
            }
        }
        if device_token is not None:
            device_query = db.session.query(Device).filter_by(
                user_id=user.id,
                device_token=device_token
            ).one_or_none()
            if device_query is None:
                device = Device(user=user, device_token=device_token,
                                refreshed=datetime.datetime.now())
                db.session.add(device)
            else:
                device_query.refreshed = datetime.datetime.now()
        db.session.commit()
        return jsonify(data)


class LogoutView(Resource):

    @staticmethod
    @jwt_required()
    def post():
        """Log the user out."""
        current_user.token_iat = None
        db.session.commit()
        return Response("Success")


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
                return redirect(url_for('auth.admin-login'))
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
            if not _is_plausible_email(form.username.data):
                return Response('Username must be a valid email address', status=400)
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
            verification_record, verification_token = _build_verification_record(
                form.username.data, is_registration=True
            )
            send_verification_email(data['username'], verification_token)
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
        if not _is_plausible_email(data['username']):
            return Response('Username must be a valid email address', status=400)
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
        verification_record, verification_token = _build_verification_record(data['username'], is_registration=True)
        send_verification_email(data['username'], verification_token)
        db.session.add(verification_record)
        db.session.commit()
        return Response(f'Verification email sent to {data["username"]}.', status=200)


class EmailVerificationView(Resource):

    @staticmethod
    def post():
        data = request.get_json()
        username = data.get('username')
        token = data.get('token')
        if not username or not token:
            return Response('Verification failed. Missing username or token.', status=400)
        if ' ' in username:
            return Response('Spaces are not allowed in emails registered to ReRack', status=400)
        if not _is_plausible_email(username):
            return Response(f'{username} is not a valid email address for use with ReRack', status=400)
        if not re.fullmatch(r'[0-9A-Za-z_\-]+', token):
            return Response(f'Invalid token', status=400)
        token_hash = generate_password_hash(token)
        verification_record = db.session.query(UserVerification).filter_by(
            username=username, token_hash=token_hash,
        ).one_or_none()
        if verification_record is None:
            return Response('Verification failed.', status=400)
        if verification_record.used:
            return Response('This verification link has been used already.', status=400)
        now = int(time.time())
        if now > verification_record.expiration_timestamp:
            return Response(
                'Verification link has expired. '
                'Please request a new verification link.',
                status=400
            )
        user = db.session.query(User).filter_by(username=username).one_or_none()
        if user is None:
            return Response('Verification failed. User not found.', status=400)
        user.verified = True
        verification_record.used = True
        db.session.commit()
        return Response(f'Success! {username} has been verified.', status=200)


class RequestVerificationEmailView(Resource):

    @staticmethod
    @jwt_required()
    def post():
        username = current_user.username
        if current_user.verified:
            return Response('User is already verified', status=403)
        now = int(time.time())
        active_records = db.session.query(UserVerification).filter_by(
            username=username, used=False).filter(
            now < UserVerification.expiration_timestamp
        ).all()
        if len(active_records) > 3:
            next_expiry = min(record.expiration_timestamp for record in active_records)
            delta_seconds = max(2, next_expiry - now)
            if delta_seconds < 120:
                delay_string = f'{delta_seconds} seconds'
            elif delta_seconds < 7200:
                delay_string = f'{(delta_seconds // 60) + 1} minutes'
            elif delta_seconds < 2 * 86400:
                delay_string = f'{(delta_seconds // 3600) + 1} hours'
            else:
                delay_string = f'{(delta_seconds // 86400) + 1} days'
            return Response(
                'Multiple verification emails have already been sent. '
                f'Please check your spam and try again in {delay_string}',
                status=400
            )
        verification_record, verification_token = _build_verification_record(username, is_registration=True)
        send_verification_email(username, verification_token)
        db.session.add(verification_record)
        db.session.commit()
        return Response('Verification email sent.', status=200)


class PasswordResetView(Resource):

    @staticmethod
    def get():
        raw_username = request.args.get('username')
        raw_token = request.args.get('token')
        if raw_username is not None and raw_token is not None:
            username = urllib.parse.unquote(raw_username)
            token = urllib.parse.unquote(raw_token)
            form_data = MultiDict([('username', username), ('token', token)])
            print(form_data)
            form = PasswordResetForm(formdata=form_data)
            return Response(render_template('auth/reset_password.html', title='Reset Password', form=form), status=200)
        return Response('Unexpected parameters.', status=400)

    @staticmethod
    def post():
        form = PasswordResetForm()
        if form.validate_on_submit():
            username = form.username.data
            new_password = form.new_password.data
            confirm_password = form.confirm_password.data
            token = form.token.data
            if new_password != confirm_password:
                return Response('Passwords do not match', status=400)
            verification_records = db.session.query(UserVerification).filter_by(
                username=username
            ).filter(
                UserVerification.expiration_timestamp > int(time.time())
            ).all()
            verification_record = None
            for record in verification_records:
                if check_password_hash(record.token_hash, token):
                    verification_record = record
                    break
            if verification_record is None:
                # This is possibly a lie. If the user submitted without requesting a
                # password reset, then there would be no matching token.
                return Response('The password reset link has expired.', status=400)
            if verification_record.used:
                return Response('Error. This link has already been used.', status=400)
            user = db.session.query(User).filter_by(username=username).one_or_none()
            if user is None:
                return Response(f'User with username {username} not found.', status=400)
            if not user.verified:
                return Response('The user is not verified. Cannot reset password.', status=400)
            user.set_password(new_password)
            verification_record.used = True
            db.session.commit()
            return Response(f'Success! Password has been reset for {form.username.data}', status=200)
        else:
            return Response('Invalid form submission', status=400)


class RequestPasswordResetView(Resource):

    @staticmethod
    def post(username):
        now = int(time.time())
        user = db.session.query(User).filter_by(username=username).one_or_none()
        if user is None:
            return Response('Error. User does not exist.', status=400)
        if not user.verified:
            return Response('Error. Cannot reset the password of an unverified user.', status=400)
        active_records = db.session.query(UserVerification).filter_by(
            username=username, used=False
        ).filter(
            UserVerification.expiration_timestamp > now
        ).all()
        if len(active_records) > 3:
            next_expiry = min(record.expiration_timestamp for record in active_records)
            delta_seconds = max(2, next_expiry - now)
            if delta_seconds < 120:
                delay_string = f'{delta_seconds} seconds'
            elif delta_seconds < 7200:
                delay_string = f'{(delta_seconds // 60) + 1} minutes'
            elif delta_seconds < 2 * 86400:
                delay_string = f'{(delta_seconds // 3600) + 1} hours'
            else:
                delay_string = f'{(delta_seconds // 86400) + 1} days'
            return Response(
                'Multiple password reset emails have already been sent. '
                f'Please check your spam and try again in {delay_string}',
                status=400
            )
        verification_record, token = _build_verification_record(
            username, is_registration=False)
        send_password_reset_email(username, token)
        db.session.add(verification_record)
        db.session.commit()
        return Response('Password reset email sent')


def _is_plausible_email(email_to_verify):
    basic_email_pattern = r'.+@.+\..+'
    email_max_len = 320
    if len(email_to_verify) > email_max_len:
        return False
    if not re.match(basic_email_pattern, email_to_verify):
        return False
    return True


def _build_verification_record(email_address, is_registration=True):
    verification_token = token_urlsafe()
    token_hash = generate_password_hash(verification_token)
    now = int(time.time())
    if is_registration:
        expiration_timestamp = now + REGISTRATION_VERIFICATION_SECONDS
    else:
        expiration_timestamp = now + PASSWORD_RESET_VERIFICATION_SECONDS
    verification_record = UserVerification(
        username=email_address,
        token_hash=token_hash,
        expiration_timestamp=expiration_timestamp,
        used=False,
    )
    return verification_record, verification_token


def send_verification_email(email_address, token):
    url_parameters = {'username': email_address, 'token': token}
    path = '/api/verify'
    query = urllib.parse.urlencode(url_parameters)
    verification_link = f'{current_app.config["ROOT_URL"]}{path}?{query}'
    message = \
        f'''
        Welcome to ReRack. Please follow the link to complete your account registration.\n\n
        {verification_link} \n\n
        If you did not register an account with ReRack, then please disregard this email.
        '''
    try:
        mail.send_mail(
            'ReRack Email Verification',
            message=message,
            from_email='rerack-noreply@finnlidbetter.com',
            recipient_list=[email_address],
        )
    except SMTPException:
        current_app.logger.exception('Error sending verification email.')
        raise


def send_password_reset_email(email_address, token):
    url_parameters = {'username': email_address, 'token': token}
    path = '/reset-password'
    query = urllib.parse.urlencode(url_parameters)
    password_reset_link = f'{current_app.config["ROOT_URL"]}{path}?{query}'
    message = \
        f'''
        Password reset requested for ReRack user {email_address}. Please follow the link to reset your 
        password.\n\n
        {password_reset_link}\n\n
        If you did not request a password reset, then please disregard this email.
        '''
    try:
        mail.send_mail(
            'ReRack Password Reset',
            message=message,
            from_email='rerack-noreply@finnlidbetter.com',
            recipient_list=[email_address],
        )
    except SMTPException:
        current_app.logger.exception('Error sending verification email.')
        raise

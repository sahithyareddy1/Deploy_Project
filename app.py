from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from pymongo import MongoClient
import face_recognition
import os
import secrets
from werkzeug.utils import secure_filename
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import traceback
import numpy as np

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

def get_db_connection():
    global client  # Declare client as global
    try:
        client = MongoClient('mongodb+srv://sahithyareddy:Sony%402023@smartvoting.kwhts.mongodb.net/?retryWrites=true&w=majority&appName=SmartVoting')
        # Return only voting_data database
        voting_data_db = client['voting_data']
        return voting_data_db
    except Exception as e:
        print(f"Database connection error: {e}")
        return None

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
    
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

ADMIN_USERNAME = "adminvoter"
ADMIN_PASSWORD = generate_password_hash("admin@123")

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            flash('Please login as admin first', 'error')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    if 'admin_logged_in' not in session:
        return redirect(url_for('admin_login'))
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if 'admin_logged_in' in session:
        return redirect(url_for('admin_dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD, password):
            session['admin_logged_in'] = True
            flash('Welcome Admin!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid credentials', 'error')
            
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    flash('Logged out successfully', 'success')
    return redirect(url_for('admin_login'))

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    db = get_db_connection()
    voters = list(db.voters.find({}, {"_id": 0}))
    return render_template('admin_dashboard.html', voters=voters)

@app.route('/voters')
@admin_required
def voter_list():
    try:
        voting_data_db = get_db_connection()
        voters = list(voting_data_db.voters.find({}, {'_id': 0}))
        print(f"Fetched voters: {voters}")
        return render_template('voter_list.html', voters=voters)
    except Exception as e:
        print(f"Error fetching voters: {e}")
        flash('Error fetching voters list', 'error')
        return render_template('voter_list.html', voters=[])

@app.route('/add_voter', methods=['GET', 'POST'])
@admin_required
def add_voter():
    if request.method == 'POST':
        unique_id = request.form.get('unique_id')
        ec_id = request.form.get('ec_id')
        
        if not unique_id or not ec_id:
            flash('Please provide both Unique ID and EC ID', 'error')
            return redirect(url_for('add_voter'))
        
        voting_data_db = get_db_connection()
        
        # Check for duplicate Voter ID
        if voting_data_db.voters.find_one({"unique_id": unique_id}):
            flash(f'Voter ID {unique_id} already exists!', 'error')
            return redirect(url_for('add_voter'))
            
        # Check for duplicate EC ID
        if voting_data_db.voters.find_one({"ec_id": ec_id}):
            flash(f'EC ID {ec_id} already exists!', 'error')
            return redirect(url_for('add_voter'))

        if 'image' not in request.files:
            flash('No image file provided', 'error')
            return redirect(url_for('add_voter'))
            
        image_file = request.files['image']
        
        if image_file.filename == '':
            flash('No image selected', 'error')
            return redirect(url_for('add_voter'))
            
        if not allowed_file(image_file.filename):
            flash('Invalid file type. Please upload a JPG, JPEG, or PNG image.', 'error')
            return redirect(url_for('add_voter'))

        filename = secure_filename(f"{unique_id}.{image_file.filename.rsplit('.', 1)[1].lower()}")
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        image_file.save(image_path)
        
        try:
            # Process face encoding
            image = face_recognition.load_image_file(image_path)
            face_locations = face_recognition.face_locations(image)
            
            if not face_locations:
                os.remove(image_path)
                flash('No face detected in the uploaded image', 'error')
                return redirect(url_for('add_voter'))
            
            encodings = face_recognition.face_encodings(image, face_locations)
            if not encodings:
                os.remove(image_path)
                flash('Could not process facial features', 'error')
                return redirect(url_for('add_voter'))
                
            new_encoding = encodings[0]

            # Check for duplicate faces
            existing_voters = voting_data_db.voters.find({})
            for voter in existing_voters:
                if 'encoding' in voter:
                    try:
                        existing_encoding = np.array(voter['encoding'])
                        face_distance = face_recognition.face_distance([existing_encoding], new_encoding)[0]
                        if face_distance < 0.6:  # Threshold for face similarity
                            os.remove(image_path)
                            flash('This face already exists in the database!', 'error')
                            return redirect(url_for('add_voter'))
                    except Exception as e:
                        print(f"Error comparing faces: {e}")
                        continue

            # Prepare voter data
            voter_data = {
                "unique_id": unique_id,
                "ec_id": ec_id,
                "encoding": new_encoding.tolist(),
                "image_path": filename,
                "registration_date": datetime.now(),
                "is_verified": False
            }
            
            # Create unique indexes
            voting_data_db.voters.create_index([("unique_id", 1)], unique=True)
            voting_data_db.voters.create_index([("ec_id", 1)], unique=True)
            
            # Insert voter data
            try:
                voting_data_db.voters.insert_one(voter_data)
                flash(f'Voter {unique_id} registered successfully!', 'success')
                return redirect(url_for('voter_list'))
            except Exception as e:
                os.remove(image_path)
                if "duplicate key error" in str(e).lower():
                    flash('Duplicate voter information detected!', 'error')
                else:
                    flash(f'Error registering voter: {str(e)}', 'error')
                return redirect(url_for('add_voter'))
                
        except Exception as e:
            if os.path.exists(image_path):
                os.remove(image_path)
            flash(f'Error processing image: {str(e)}', 'error')
            return redirect(url_for('add_voter'))
    
    return render_template('add_voter.html')

@app.route('/bulk_upload', methods=['GET', 'POST'])
@admin_required
def bulk_upload():
    if request.method == 'POST':
        if 'csv_file' not in request.files:
            flash('No CSV file provided', 'error')
            return redirect(url_for('bulk_upload'))
            
        flash('Bulk upload functionality will be implemented soon', 'info')
        return redirect(url_for('voter_list'))
    
    return render_template('bulk_upload.html')

@app.route('/delete_voter/<unique_id>', methods=['POST'])
@admin_required
def delete_voter(unique_id):
    try:
        voting_data_db = get_db_connection()
        result = voting_data_db.voters.delete_one({"unique_id": unique_id})
        
        if result.deleted_count > 0:
            return jsonify({"status": "success", "message": f"Voter {unique_id} deleted successfully"})
        else:
            return jsonify({"status": "error", "message": "Voter not found"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/vote_results')
def vote_results():
    db = get_db_connection()
    try:
        votes = list(db.votes.find())
        
        # Process votes and count
        party_counts = {}
        for vote in votes:
            vote['_id'] = str(vote['_id'])
            if isinstance(vote.get('timestamp'), datetime):
                vote['timestamp'] = vote['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            
            party_id = vote.get('party_id')
            party_counts[party_id] = party_counts.get(party_id, 0) + 1

        # Determine winner or tie
        result = {'status': None, 'data': None}
        if party_counts:
            max_votes = max(party_counts.values())
            winning_parties = [
                (party_id, votes) 
                for party_id, votes in party_counts.items() 
                if votes == max_votes
            ]
            
            if len(winning_parties) > 1:
                result = {
                    'status': 'tie',
                    'data': [
                        {'party_id': party_id, 'votes': vote_count}
                        for party_id, vote_count in winning_parties
                    ]
                }
            else:
                result = {
                    'status': 'winner',
                    'data': {
                        'party_id': winning_parties[0][0],
                        'votes': winning_parties[0][1]
                    }
                }

        return render_template('vote_results.html', 
                             votes=votes, 
                             party_counts=party_counts,
                             result=result)

    except Exception as e:
        print(f"Error in vote_results: {str(e)}")
        return f"Error fetching data: {str(e)}"

@app.route('/cast_vote', methods=['POST'])
def cast_vote():
    try:
        # Extract vote data from the request
        unique_id = request.form.get('unique_id')
        ec_id = request.form.get('ec_id')
        party_id = request.form.get('party_id')
        
        if not unique_id or not ec_id or not party_id:
            return jsonify({'status': 'error', 'message': 'Missing required fields'}), 400
        
        # Get the database connection
        voting_data_db = get_db_connection()
        
        # Check if this voter has already voted
        existing_vote = voting_data_db.votes.find_one({'unique_id': unique_id})
        if existing_vote:
            return jsonify({'status': 'error', 'message': 'This voter has already cast a vote'}), 400
        
        # Save the vote
        vote_data = {
            'unique_id': unique_id,
            'ec_id': ec_id,
            'party_id': party_id,
            'timestamp': datetime.now()
        }
        
        result = voting_data_db.votes.insert_one(vote_data)
        
        if result.inserted_id:
            return jsonify({'status': 'success', 'message': 'Vote cast successfully'})
        else:
            return jsonify({'status': 'error', 'message': 'Failed to record vote'}), 500
            
    except Exception as e:
        print(f"Error casting vote: {e}")
        print(traceback.format_exc())
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Voter verification and voting interface
@app.route('/verify_voter', methods=['GET', 'POST'])
def verify_voter():
    if request.method == 'POST':
        # This would be the route to verify voters using facial recognition
        # For now, we'll implement a simple ID-based verification
        unique_id = request.form.get('unique_id')
        ec_id = request.form.get('ec_id')
        
        if not unique_id or not ec_id:
            flash('Please provide both Unique ID and EC ID', 'error')
            return redirect(url_for('verify_voter'))
            
        voting_data_db = get_db_connection()
        
        # Check if voter exists
        voter = voting_data_db.voters.find_one({"unique_id": unique_id, "ec_id": ec_id})
        
        if not voter:
            flash('Voter not found or credentials do not match', 'error')
            return redirect(url_for('verify_voter'))
            
        # Check if voter has already voted
        existing_vote = voting_data_db.votes.find_one({"unique_id": unique_id})
        if existing_vote:
            flash('You have already cast your vote', 'warning')
            return redirect(url_for('verify_voter'))
            
        # Set session for verified voter
        session['verified_voter'] = {
            'unique_id': unique_id,
            'ec_id': ec_id
        }
        
        return redirect(url_for('voting_booth'))
        
    return render_template('verify_voter.html')

@app.route('/voting_booth')
def voting_booth():
    # Check if voter is verified
    if 'verified_voter' not in session:
        flash('Please verify your identity first', 'error')
        return redirect(url_for('verify_voter'))
        
    # Get voter details from session
    voter = session['verified_voter']
    
    # Mock party data - in a real app, this would come from your database
    parties = [
        {"id": "1", "name": "Party A", "symbol": "🟠"},
        {"id": "2", "name": "Party B", "symbol": "🟢"},
        {"id": "3", "name": "Party C", "symbol": "🔵"}
    ]
    
    return render_template('voting_booth.html', voter=voter, parties=parties)

@app.route('/submit_vote', methods=['POST'])
def submit_vote():
    # Check if voter is verified
    if 'verified_voter' not in session:
        return jsonify({'status': 'error', 'message': 'Not verified'}), 401
        
    # Get voter details from session
    voter = session['verified_voter']
    
    # Get selected party
    party_id = request.form.get('party_id')
    
    if not party_id:
        return jsonify({'status': 'error', 'message': 'No party selected'}), 400
        
    # Save the vote
    voting_data_db = get_db_connection()
    
    # Check if voter has already voted (double-check)
    existing_vote = voting_data_db.votes.find_one({"unique_id": voter['unique_id']})
    if existing_vote:
        session.pop('verified_voter', None)
        return jsonify({'status': 'error', 'message': 'You have already cast your vote'}), 400
        
    # Save the vote
    vote_data = {
        'unique_id': voter['unique_id'],
        'ec_id': voter['ec_id'],
        'party_id': party_id,
        'timestamp': datetime.now()
    }
    
    result = voting_data_db.votes.insert_one(vote_data)
    
    # Clear the session after voting
    session.pop('verified_voter', None)
    
    if result.inserted_id:
        return jsonify({'status': 'success', 'message': 'Your vote has been cast successfully'})
    else:
        return jsonify({'status': 'error', 'message': 'Failed to record your vote'}), 500

if __name__ == '__main__':
    app.run(debug=True)
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
import sqlite3
import os
from werkzeug.utils import secure_filename
from database import create_table
import threading
import time
import webbrowser
from threading import Thread
import subprocess

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Required for flash messages

 # Create this folder in your project
#UPLOAD_FOLDER = '\\static\\uploads' 
#UPLOAD_FOLDER = os.path.join('static', 'uploads')
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
# Print current working directory and template folder
print("Current Working Directory:", os.getcwd())
print("Template Folder:", app.template_folder)
print("Static Folder Path:", app.static_folder)

# Global variable to control shutdown
shutdown_flag = False

create_table()

@app.route('/')
def index():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    # Fetch all vehicles
    cursor.execute("SELECT * FROM vehicles")
    vehicles = cursor.fetchall()

    # Create a list to store vehicle details with the first photo added
    vehicle_list = []
    columns = [column[0] for column in cursor.description]  # Extract column names

    for vehicle in vehicles:
        # Create a dictionary from the tuple by zipping column names with row values
        vehicle_dict = dict(zip(columns, vehicle))

        # Fetch the first photo for the vehicle
        cursor.execute("SELECT photo FROM vehicle_photos WHERE vehicle_id=?", (vehicle_dict['id'],))
        photos = cursor.fetchall()
        vehicle_dict['first_photo'] = photos[0][0] if photos else None  # Set the first photo for each vehicle

        # Add the vehicle (with the first photo) to the list
        vehicle_list.append(vehicle_dict)

    conn.close()
    return render_template('index.html', vehicles=vehicle_list)

@app.route('/add', methods=['GET', 'POST'])
def add_vehicle():
    if request.method == 'POST':
        # Get the vehicle details
        marca = request.form.get('marca')
        modelo = request.form.get('modelo')
        CC = request.form.get('CC')
        cor = request.form.get('cor')
        matricula = request.form.get('matricula')
        ano = request.form.get('ano')
        num_lugares = request.form.get('num_lugares')
        local_garagem = request.form.get('local_garagem')
        estado_geral = request.form.get('estado_geral')

        # Connect to the database
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()

        # Insert the vehicle record
        cursor.execute('''
            INSERT INTO vehicles (marca, modelo, CC, cor, matricula, ano, num_lugares, local_garagem, estado_geral)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (marca, modelo, CC, cor, matricula, ano, num_lugares, local_garagem, estado_geral))
        conn.commit()

        # Get the last inserted vehicle id
        vehicle_id = cursor.lastrowid

        # Handle multiple photos
        photos = request.files.getlist('photos')  # This will return a list of file objects
        for photo in photos:
            if photo and photo.filename:
                filename = secure_filename(photo.filename)
                photo_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                print("Saving photo:", photo_path)  # Debugging line
                photo.save(photo_path)

                # Insert the photo into the vehicle_photos table
                cursor.execute(
                    """
                    INSERT INTO vehicle_photos (vehicle_id, photo)
                    VALUES (?, ?)
                    """,
                    (vehicle_id, filename),
                )

        # Commit the changes and close the connection
        conn.commit()
        conn.close()

        return redirect(url_for('index'))  # Redirect to the vehicle list

    return render_template('create_vehicle.html')  # Render the form template

@app.route('/edit/<int:vehicle_id>', methods=['GET', 'POST'])
def edit_vehicle(vehicle_id):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    # Fetch the vehicle details
    cursor.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,))
    vehicle = cursor.fetchone()

    if vehicle is None:
        # If the vehicle does not exist, return an error
        flash('Vehicle not found', 'error')
        return redirect(url_for('index'))

    # Convert the vehicle tuple into a dictionary
    columns = [column[0] for column in cursor.description]  # Get column names
    vehicle_dict = dict(zip(columns, vehicle))  # Create dictionary from tuple

    # Fetch the associated photos for the vehicle
    cursor.execute("SELECT photo FROM vehicle_photos WHERE vehicle_id=?", (vehicle_id,))
    photos = cursor.fetchall()
    vehicle_dict['photos'] = [photo[0] for photo in photos]  # Add all photos to the vehicle

    if request.method == 'POST':
        # Handle the form submission to update the vehicle details
        marca = request.form['marca']
        modelo = request.form['modelo']
        CC = request.form['CC']
        cor = request.form['cor']
        matricula = request.form['matricula']
        ano = request.form['ano']
        num_lugares = request.form['num_lugares']
        local_garagem = request.form['local_garagem']
        estado_geral = request.form['estado_geral']
        
        # Update vehicle details in the database
        cursor.execute(''' 
            UPDATE vehicles SET marca=?, modelo=?, CC=?, cor=?, matricula=?, ano=?, num_lugares=?, local_garagem=?, estado_geral=? WHERE id=?
        ''', (marca, modelo, CC, cor, matricula, ano, num_lugares, local_garagem, estado_geral, vehicle_id))
        conn.commit()

        # Handle updating the photos
        photos_to_delete = request.form.getlist('photos_to_delete')  # Photos marked for deletion
        if photos_to_delete:
            for photo in photos_to_delete:
                cursor.execute("DELETE FROM vehicle_photos WHERE photo=? AND vehicle_id=?", (photo, vehicle_id))
        
        # Save new photos if any
        new_photos = request.files.getlist('photos')
        for photo in new_photos:
            if photo and photo.filename:
                filename = secure_filename(photo.filename)
                photo_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                photo.save(photo_path)

                # Insert the new photo into the database
                cursor.execute(
                    "INSERT INTO vehicle_photos (vehicle_id, photo) VALUES (?, ?)",
                    (vehicle_id, filename),
                )
        
        conn.commit()
        conn.close()

        flash('Vehicle updated successfully!', 'success')
        return redirect(url_for('index'))  # Redirect to the list of vehicles

    conn.close()
    return render_template('edit_vehicle.html', vehicle=vehicle_dict)


@app.route('/delete/<int:vehicle_id>', methods=['GET', 'POST'])
def delete_vehicle(vehicle_id):
    # Connect to the database
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    # Get all photos associated with the vehicle
    cursor.execute("SELECT photo FROM vehicle_photos WHERE vehicle_id=?", (vehicle_id,))
    photos = cursor.fetchall()

    # Delete the vehicle from the vehicle_photos table
    cursor.execute("DELETE FROM vehicle_photos WHERE vehicle_id=?", (vehicle_id,))
    
    # Delete the vehicle itself from the vehicles table
    cursor.execute("DELETE FROM vehicles WHERE id=?", (vehicle_id,))
    
    # Commit the changes
    conn.commit()

    # Delete the photos from the filesystem
    for photo in photos:
        filename = secure_filename(photo[0])
        photo_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(photo_path):
            os.remove(photo_path)

    conn.close()

    flash('Vehicle and its photos deleted successfully!', 'success')
    return redirect(url_for('index'))  # Redirect to the vehicle list page

@app.route('/shutdown', methods=['POST'])
def shutdown():
    global shutdown_flag
    shutdown_flag = True  # Set the flag to indicate shutdown
    return jsonify({"message": "Server will shut down after processing current requests..."}), 200

@app.route('/static/uploads/<filename>')
def uploaded_file(filename):
    print("Serving file:", filename)
    print("Serving config:", app.config['UPLOAD_FOLDER'])
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

def run():
    global shutdown_flag
    while not shutdown_flag:
        time.sleep(1)  # Keep the server running
    print("Shutting down...")  # Placeholder for actual shutdown code
    os._exit(0)  # Forcefully exit the program

if __name__ == "__main__":

    threading.Thread(target=run, daemon=True).start()

    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

    webbrowser.open("http://127.0.0.1:5000", new=1)

    app.run(debug=True, host='127.0.0.1', port=5000)

    # Start the Flask app in a separate thread
    # Open the default web browser after the server starts
    
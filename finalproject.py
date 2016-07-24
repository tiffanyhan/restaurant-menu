from flask import Flask, render_template, flash, url_for, redirect, request, jsonify
app = Flask(__name__)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database_setup import Base, Restaurant, MenuItem, User

# imports for Oauth2.0
from flask import session as login_session
import random, string

from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
import httplib2
import json
from flask import make_response
import requests

CLIENT_ID = json.loads(
	open('client_secrets.json', 'r').read())['web']['client_id']

def getSession():
	engine = create_engine('sqlite:///restaurantmenuwithusers.db')
	Base.metadata.bind = engine
	DBSession = sessionmaker(bind=engine)
	session = DBSession()
	return session

def checkAuth():
	auth = ''
	if 'username' in login_session:
		auth = True
	else:
		auth = False
	return auth

def checkCreator(restaurant):
	creator = ''
	if login_session['user_id'] == restaurant.user_id:
		creator = True
	else:
		creator = False
	return creator

# User helper functions
def getUserID(email):
	session = getSession()
	try:
		user = session.query(User).filter_by(email = email).one()
		return user.user_id
	except:
		return None

def getUserInfo(user_id):
	session = getSession()
	user = session.query(User).filter_by(user_id = user_id).one()
	return user

def createUser(login_session):
	newUser = User(name = login_session['username'],
					email = login_session['email'],
					picture = login_session['picture'])
	session = getSession()
	session.add(newUser)
	session.commit()
	user = session.query(User).filter_by(email = login_session['email']).one()
	return user.user_id

# All of our routes and handlers
@app.route('/login/')
def showLogin():
	state = ''.join(random.choice(string.ascii_uppercase + string.digits) for x in xrange(32))
	login_session['state'] = state
	return render_template('login.html', state=state)

@app.route('/gconnect', methods=['POST'])
def gconnect():
	# validate state token
	if request.args.get('state') != login_session['state']:
		response = make_response(json.dumps('Invalid state parameter.'), 401)
		response.headers['Content-Type'] = 'application/json'
		return response
	# Obtain authorization code
	code = request.data

	try:
		# Upgrade the authorization code into a credentials object
		oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
		oauth_flow.redirect_uri = 'postmessage'
		credentials = oauth_flow.step2_exchange(code)
	except FlowExchangeError:
		response = make_response(
			json.dumps('Failed to upgrade the authorization code.'), 401)
		response.headers['Content-Type'] = 'application/json'
		return response

	# Check that the access token is valid.
	access_token = credentials.access_token
	url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s' % access_token)
	h = httplib2.Http()
	result = json.loads(h.request(url, 'GET')[1])
	# If there was an error in the access token info, abort.
	if result.get('error') is not None:
		response = make_response(json.dumps(result.get('error')), 500)
		response.headers['Content-Type'] = 'application/json'
		return response

	# Verify that the access token is used for the intended user.
	gplus_id = credentials.id_token['sub']
	if result['user_id'] != gplus_id:
		response = make_response(
			json.dumps("Token's user ID doesn't match given user ID."), 401)
		response.headers['Content-Type'] = 'application/json'
		return response

	# Verify that the access token is valid for this app.
	if result['issued_to'] != CLIENT_ID:
		response = make_response(
			json.dumps("Token's client ID does not match app's."), 401)
		print "Token's client ID doesn't match app's."
		response.headers['Content-Type'] = 'application/json'
		return response

	stored_credentials = login_session.get('credentials')
	stored_gplus_id = login_session.get('gplus_id')
	if stored_credentials is not None and gplus_id == stored_gplus_id:
		response = make_response(json.dumps('Current user is already connected.'), 200)
		response.headers['Content-Type'] = 'application/json'
		return response

	# Store the access token in the session for later use.
	login_session['credentials'] = credentials
	login_session['gplus_id'] = gplus_id

	# Get user info
	userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
	params = {'access_token': credentials.access_token, 'alt': 'json'}
	answer = requests.get(userinfo_url, params=params)

	data = answer.json()

	login_session['username'] = data['name']
	login_session['picture'] = data['picture']
	login_session['email'] = data['email']

	# see if user exists, if not then make a new one
	user_id = getUserID(login_session['email'])
	if not user_id:
		user_id = createUser(login_session)
	login_session['user_id'] = user_id

	output = ''
	output += '<h1>Welcome, '
	output += login_session['username']
	output += '!</h1>'
	output += '<img src="'
	output += login_session['picture']
	output += '" style = "width:300px; height:300px; border-radius:150px; -webkit-border-radius:150px; -moz-border-radius:150px;">'
	flash("you are now logged in as %s" % login_session['username'])
	print "done!"
	return output

@app.route('/gdisconnect/')
def gdisconnect():
	# Only disconnect a connected user.
	credentials = login_session.get('credentials')
	if credentials is None:
		response = make_response(json.dumps('Current user not connected.'), 401)
		response.headers['Content-Type'] = 'application/json'
		return response

	# Execute HTTP GET request to revoke current token
	access_token = credentials.access_token
	url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % access_token
	h = httplib2.Http()
	result = h.request(url, 'GET')[0]
	response = requests.get(url).json()

	if response['error_description'] == 'Token expired or revoked' or result['status'] == '200':
		# Reset the user's session.
		del login_session['credentials']
		del login_session['gplus_id']
		del login_session['username']
		del login_session['email']
		del login_session['picture']

		response = make_response(json.dumps('Successfully disconnected.'), 200)
		response.headers['Content-Type'] = 'application/json'
		return response

	else:
		# For whatever reason, the given token was invalid.
		response = make_response(
			json.dumps('Failed to revoke token for given user.'), 400)
		response.headers['Content-Type'] = 'application/json'
		return response

@app.route('/')
@app.route('/restaurants/')
def showRestaurants():
	session = getSession()
	restaurants = session.query(Restaurant).all()

	if restaurants == []:
		flash('You currently have no restaurants to list')

	session.close()
	return render_template('restaurants.html', restaurants = restaurants)

@app.route('/restaurant/new/', methods = ['GET', 'POST'])
def newRestaurant():
	if request.method == 'POST':
		newName = request.form['name']
		user_id = login_session['user_id']

		if not newName:
			error = 'Please enter in a new restaurant name'
			return render_template('newRestaurant.html', error=error)

		else:
			session = getSession()
			newRestaurant = Restaurant(name = newName,
										user_id = login_session['user_id'])
			session.add(newRestaurant)
			session.commit()
			flash("New restaurant created!")

			session.close()
			return redirect(url_for('showRestaurants'))

	else:
		if checkAuth() == False:
			return redirect(url_for('showLogin'))
		else:
			return render_template('newRestaurant.html')

@app.route('/restaurant/<int:restaurant_id>/edit/', methods = ['GET', 'POST'])
def editRestaurant(restaurant_id):
	session = getSession()
	restaurantToEdit = session.query(Restaurant).filter_by(restaurant_id = restaurant_id).one()

	if request.method == 'POST' and checkCreator(restaurantToEdit):
		editedName = request.form['name']

		if not editedName:
			error = 'Please enter in a new restaurant name'
			return render_template('editRestaurant.html',
									restaurant_id = restaurant_id,
									restaurant = restaurantToEdit,
									error=error)

		else:
			restaurantToEdit.name = editedName
			session.add(restaurantToEdit)
			session.commit()
			flash("Restaurant renamed")

			session.close()
			return redirect(url_for('showMenu', restaurant_id = restaurant_id))


	else:
		session.close()
		if not checkAuth():
			return redirect(url_for('showLogin'))
		elif not checkCreator(restaurantToEdit):
			flash("You must be the creator of this restaurant menu in order to make changes.")
			return redirect(url_for('showMenu', restaurant_id = restaurant_id))
		else:
			return render_template('editRestaurant.html',
									restaurant_id = restaurant_id,
									restaurant = restaurantToEdit)

@app.route('/restaurant/<int:restaurant_id>/delete/', methods = ['GET', 'POST'])
def deleteRestaurant(restaurant_id):
	session = getSession()
	restaurantToDelete = session.query(Restaurant).filter_by(restaurant_id = restaurant_id).one()

	if request.method == 'POST':
		session.delete(restaurantToDelete)
		session.commit()
		flash("Restaurant deleted")

		session.close()
		return redirect(url_for('showRestaurants'))

	else:
		if not checkAuth():
			return redirect(url_for('showLogin'))
		elif not checkCreator(restaurantToDelete):
			flash("You must be the creator of this restaurant menu in order to make changes.")
			return redirect(url_for('showMenu', restaurant_id = restaurant_id))
		else:
			session.close()
			return render_template('deleteRestaurant.html',
									restaurant_id = restaurant_id,
									restaurant = restaurantToDelete)

@app.route('/restaurant/<int:restaurant_id>/')
@app.route('/restaurant/<int:restaurant_id>/menu/')
def showMenu(restaurant_id):
	session = getSession()
	restaurant = session.query(Restaurant).filter_by(restaurant_id = restaurant_id).one()
	items = session.query(MenuItem).filter_by(restaurant_id = restaurant_id).all()

	appetizers = []
	entrees = []
	desserts = []
	beverages = []

	for item in items:
		if item.course == 'Appetizer':
			appetizers.append(item)
		elif item.course == 'Entree':
			entrees.append(item)
		elif item.course == 'Dessert':
			desserts.append(item)
		elif item.course == 'Beverage':
			beverages.append(item)

	if not checkAuth() or not checkCreator(restaurant):
		creator = getUserInfo(restaurant.user_id)
		session.close()
		return render_template('publicmenu.html',
								restaurant_id = restaurant_id,
								restaurant = restaurant,
								appetizers = appetizers,
								entrees = entrees,
								desserts = desserts,
								beverages = beverages,
								creator = creator)

	else:
		if items == []:
			flash('You currently have no items in this menu')

		if appetizers == []:
			flash('You currently have no appetizers in this menu')
		if entrees == []:
			flash('You currently have no entrees in this menu')
		if desserts == []:
			flash('You currently have no desserts in this menu')
		if beverages == []:
			flash('You currently have no beverages in this menu')

		session.close()
		return render_template('menu.html',
								restaurant_id = restaurant_id,
								restaurant = restaurant,
								appetizers = appetizers,
								entrees = entrees,
								desserts = desserts,
								beverages = beverages)

@app.route('/restaurant/<int:restaurant_id>/menu/new/', methods = ['GET', 'POST'])
def newMenuItem(restaurant_id):
	session = getSession()
	restaurant = session.query(Restaurant).filter_by(restaurant_id = restaurant_id).one()

	if request.method == 'POST' and checkCreator(restaurant):
		name = request.form['name'].encode('latin-1')
		price = request.form['price'].encode('latin-1')
		description = request.form['description'].encode('latin-1')
		course = request.form['course'].encode('latin-1')


		if name and price and description and course:
			newItem = MenuItem(name = name,
								course = course,
								description = description,
								price = price,
								restaurant_id = restaurant_id)
			session.add(newItem)
			session.commit()
			flash("New menu item created!")

			session.close()
			return redirect(url_for('showMenu', restaurant_id = restaurant_id))

	else:
		session.close()
		if not checkAuth():
			return redirect(url_for('showLogin'))

		elif not checkCreator(restaurant):
			flash("You must be the creator of this restaurant menu in order to make changes.")
			return redirect(url_for('showMenu', restaurant_id = restaurant_id))

		else:
			return render_template('newMenuItem.html',
									restaurant_id = restaurant_id,
									restaurant = restaurant)

@app.route('/restaurant/<int:restaurant_id>/menu/<int:menu_id>/edit/', methods = ['GET', 'POST'])
def editMenuItem(restaurant_id, menu_id):
	session = getSession()
	restaurant = session.query(Restaurant).filter_by(restaurant_id = restaurant_id).one()
	itemToBeEdited = session.query(MenuItem).filter_by(menu_id = menu_id).one()

	if request.method == 'POST' and checkCreator(restaurant):
		if request.form['name']:
			itemToBeEdited.name = request.form['name']
		if request.form['course']:
			itemToBeEdited.course = request.form['course']
		if request.form['description']:
			itemToBeEdited.description = request.form['description']
		if request.form['price']:
			itemToBeEdited.price = request.form['price']

		session.add(itemToBeEdited)
		session.commit()
		flash("Menu item edited")

		session.close()
		return redirect(url_for('showMenu', restaurant_id = restaurant_id))

	else:
		session.close()
		if not checkAuth():
			return redirect(url_for('showLogin'))
		elif not checkCreator(restaurant):
			flash("You must be the creator of this restaurant menu in order to make changes.")
			return redirect(url_for('showMenu', restaurant_id = restaurant_id))
		else:
			return render_template('editMenuItem.html',
									restaurant_id = restaurant_id,
									menu_id = menu_id,
									restaurant = restaurant,
									item = itemToBeEdited)

@app.route('/restaurant/<int:restaurant_id>/menu/<int:menu_id>/delete/', methods = ['GET', 'POST'])
def deleteMenuItem(restaurant_id, menu_id):
	session = getSession()
	restaurant = session.query(Restaurant).filter_by(restaurant_id = restaurant_id).one()
	itemToBeDeleted = session.query(MenuItem).filter_by(menu_id = menu_id).one()

	if request.method == 'POST' and checkCreator(restaurant):
		session.delete(itemToBeDeleted)
		session.commit()
		flash("Menu item deleted")

		session.close()
		return redirect(url_for('showMenu', restaurant_id = restaurant_id))

	else:
		session.close()
		if not checkAuth():
			return redirect(url_for('showLogin'))
		elif not checkCreator(restaurant):
			flash("You must be the creator of this restaurant menu in order to make changes.")
			return redirect(url_for('showMenu', restaurant_id = restaurant_id))
		else:
			return render_template('deleteMenuItem.html',
									restaurant_id = restaurant_id,
									menu_id = menu_id,
									restaurant = restaurant,
									item = itemToBeDeleted)

@app.route('/restaurants/JSON/')
def restaurantJSON():
	session = getSession()
	restaurants = session.query(Restaurant).all()

	session.close()
	return jsonify(Restaurants=[restaurant.serialize for restaurant in restaurants])

@app.route('/restaurant/<int:restaurant_id>/menu/JSON/')
def restaurantMenuJSON(restaurant_id):
	session = getSession()
	restaurant = session.query(Restaurant).filter_by(restaurant_id = restaurant_id).one()
	items = session.query(MenuItem).filter_by(restaurant_id = restaurant_id).all()

	session.close()
	return jsonify(MenuItems=[item.serialize for item in items])

@app.route('/restaurant/<int:restaurant_id>/menu/<int:menu_id>/JSON/')
def restaurantMenuItemJSON(restaurant_id, menu_id):
	session = getSession()
	item = session.query(MenuItem).filter_by(menu_id = menu_id).one()

	session.close()
	return jsonify(MenuItem=item.serialize)

if __name__ == '__main__':
	app.secret_key = 'imsosecret'
	app.debug = True
	app.run(host = '0.0.0.0', port = 5000)
import time
import threading
from sqlobject import *
from datetime import timedelta

from base.DebugHelper import *
from .CarStatuses import *		
from data.Logger import *

from model.DBHelper import DBHelper

db_helper = DBHelper( )
entity = db_helper.get_entity_class( )

class Car( entity ):

	LOG_TEMPLATE = '»»»»»»»»»» Car {} --- {}'

	DEFAULT_BATTERY_LEVEL = 10

	__counter = 0

	#_id = PrimaryKey( int, default = None, defaultSQL = None, dbName = 'id', auto = True )
	_simulator = None
	_status = StringCol( default = '', dbName = 'status' )
	_travels = MultipleJoin( 'Travel' )
	_charging_periods = MultipleJoin( 'ChargingPeriod' )
	_battery_level = FloatCol( default = None, dbName = 'battery_level' )
	_plug = ForeignKey( 'Plug', default = None, dbName = 'plug_id' )
	_lock = None

	def __init__( self, simulator ):
		super( ).__init__( )

		from .Plug import Plug

		#Car.__counter += 1				
		#elf._id = Car.__counter
		self._simulator = simulator
		self._status = CarStatuses.STATUS_READY
		#self._travels = [ ]	
		#self._charging_periods = [ ]
		self._battery_level = Car.DEFAULT_BATTERY_LEVEL		
		#self._plug = Optional( Plug, default = None, defaultSQL = None, dbName = 'car_id' )
		self._lock = threading.Lock( )

		self.get_plug( )

		#self.save();

	def reset_counter( ):
		Car.__counter = 0		

	def get_id( self ):
		return self.id

	def get_simulator( self ):
		return self._simulator

	def lock( self ):
		caller = DebugHelper.get_caller( )
		self.log_debug( 'LOCKING... (by {})'.format( caller ) )
		self._lock.acquire( )

	def unlock( self ):
		caller = DebugHelper.get_caller( )
		self.log_debug( 'UNLOCKING... (by {})'.format( caller ) )
		self._lock.release( )

	def is_busy( self ):
		is_busy = self._status != CarStatuses.STATUS_READY
		return is_busy

	def get_status( self ):
		return self._status

	def set_status( self, new_status ):
		self._status = new_status

	def get_travels( self ):
		return self._travels

	def get_charging_periods( self ):
		return self._charging_periods

	def get_battery_level( self ):
		return self._battery_level

	def set_battery_level( self, battery_level ):
		if battery_level >= 0 and battery_level <= 10:
			self._battery_level = battery_level
		elif battery_level < 0:
			self._battery_level = 0
		elif battery_level > 10:
			self._battery_level = 10
		else:
			self.log( 'Invalid battery level given!' )

	def set_plug( self, new_plug ):
		self._plug = new_plug

	def get_plug( self ):
		return self._plug

	def start_travel( self ):	
		from .events.Travel import Travel

		new_travel = Travel( self )
		self._travels.append( new_travel )
		self.set_status( CarStatuses.STATUS_TRAVELING )

	def end_travel( self ):
		self.lock( )		

		last_travel = self._travels[ -1 ]
		last_travel_battery_consumption = last_travel.get_battery_consumption( )
		battery_level = self.get_battery_level( )
		new_battery_level = battery_level - last_travel_battery_consumption
		self.set_battery_level( new_battery_level )

		self.log( 'Travel ended!' )

		self.unlock( )			

		simulator = self._simulator
		simulator.lock_current_step( )

		if simulator.can_simulate_new_actions( ) and new_battery_level < 2:

			self.log( 'Car reached <20% battery! Waiting for a available charging plug..' )										
			self._start_charging_period( )		

		else:

			self.lock( )
			self.set_status( CarStatuses.STATUS_READY )
			self.unlock( )

		simulator.unlock_current_step( )																				

	def _start_charging_period( self ):
		from .events.ChargingPeriod import ChargingPeriod

		new_charging_period = ChargingPeriod( self )
		self._charging_periods.append( new_charging_period )

	def end_charging_period( self, ended_normally ):
		self.lock( )	

		plug = self.get_plug( )
		plug.set_energy_consumption( 0 )

		if ended_normally:

			self.set_battery_level( Car.DEFAULT_BATTERY_LEVEL )

		else:

			#TODO
			pass
			
		self.set_status( CarStatuses.STATUS_READY )			

		self.log( 'Charging period ended!' )

		self.unlock( )		

	def log( self, message ):
		Logger.log( Car.LOG_TEMPLATE.format( self.id, message ) )

	def log_debug( self, message ):
		Logger.log_debug( Car.LOG_TEMPLATE.format( self.id, message ) )		

	def destroy( self ):
		for t in self._travels:
			t.destroy( )

		for c in self._charging_periods:
			c.destroy( )

	def get_data( self ):

		#with db_session( strict = False ):

		plug_id = ''
		plug_consumption = 0

		plug = self.get_plug( )		
		
		if plug:
			plug_id = plug.get_id( )
			plug_consumption = plug.get_energy_consumption( )

		return { 
			"id" : self.id,
			"status" : self.get_status( ),
			"travels" : [ t.get_data( ) for t in self._travels ],
			"charging_periods" : [ p.get_data( ) for p in self._charging_periods ],
			"battery_level" : self.get_battery_level( ),
			"plug_id": plug_id,
			"plug_consumption" : plug_consumption
		}
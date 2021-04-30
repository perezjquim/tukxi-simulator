import threading
import time
import requests
from datetime import date, datetime, timedelta

from base.BaseModelProxy import *

from data.Logger import *
from base.DebugHelper import *
from .objects.Car import *
from .objects.Plug import *
from .objects.Log import *
from .events.Travel import *
from .events.ChargingPeriod import *
from model.SimulationModel import *

class Simulation( BaseModelProxy ):

	MAIN_LOG_PREFIX = '============================'

	_cars = [ ]
	_charging_plugs = [ ]
	_logs = [ ]

	_affluence_counts = { }

	_charging_plugs_semaphore = None

	_current_step = 1
	_current_step_lock = None

	_current_datetime = None	
	_current_datetime_lock = None

	_simulator = None	
	_thread = None	

	def __init__( self, simulator ):
		super( ).__init__( 'model.SimulationModel', 'SimulationModel' )	

		self._simulator = simulator

		self._current_step = 1

		self._current_step_lock = threading.Lock( )
		self._current_datetime_lock = threading.Lock( )

	def get_simulator( self ):
		return self._simulator

	def on_start( self ):
		self.initialize_cars( )
		self.initialize_plugs( )
		self.initialize_datetime( )

		self._thread = threading.Thread( target = self.run )						
		self._thread.start( )	

	def initialize_cars( self ):
		self.log( 'Initializing cars...' )

		simulator = self._simulator
		number_of_cars = simulator.get_config_by_key( 'number_of_cars' )
		for n in range( number_of_cars ):
			self._cars.append( Car( self ) )

		self.log( 'Initializing cars... done!' )

	def initialize_datetime( self ):
		self.log( 'Initializing date...' )

		today_date = date.today( )
		today_year = today_date.year
		today_month = today_date.month
		today_day = today_date.day

		self.set_current_datetime( datetime( year = today_year, month = today_month, day = today_day ) )
		self.log( 'Date initialized as: {}'.format( self._current_datetime ) )

		self.log( 'Initializing date... done!' )

	def initialize_plugs( self ):
		self.log( 'Initializing plugs...' )

		simulator = self._simulator
		number_of_charging_plugs = simulator.get_config_by_key( 'number_of_charging_plugs' )
		for n in range( number_of_charging_plugs ):
			self._charging_plugs.append( Plug( self ) )

		self._charging_plugs_semaphore = threading.Semaphore( number_of_charging_plugs )							

		self.log( 'Initializing plugs... done!' )									

	def on_stop( self ):			
		self._end_simulation( True )	

	def run( self ):
		self.log_main( 'Simulating...' )		

		simulator = self._simulator

		sim_sampling_rate = simulator.get_config_by_key( 'sim_sampling_rate' )		
		number_of_steps = simulator.get_config_by_key( 'number_of_steps' )

		while simulator.is_simulation_running( ):

			number_of_busy_cars = 0
			total_plug_consumption = 0

			for c in self._cars:
				c.lock( )

				if c.is_busy( ):
					number_of_busy_cars += 1

				car_plug = c.get_plug( )
				if car_plug:
					plug_energy_consumption = car_plug.get_energy_consumption( )
					total_plug_consumption += plug_energy_consumption

				c.unlock( )		

			self.log( '### TOTAL PLUG CONSUMPTION: {} KW ###'.format( total_plug_consumption ) )

			should_simulate_next_step = ( self.can_simulate_new_actions( ) or number_of_busy_cars > 0 )

			if should_simulate_next_step:	

				self.log( "> Simulation step..." )		

				self.lock_current_datetime( )

				current_datetime = self.get_current_datetime( )
				current_step = self.get_current_step( )				
				if current_step > 1:
					
					minutes_per_sim_step = simulator.get_config_by_key( 'minutes_per_sim_step' )
					current_datetime += timedelta( minutes = minutes_per_sim_step )
					self.set_current_datetime( current_datetime )	

				self.unlock_current_datetime( )
				
				self.log( "( ( ( Step #{} - at: {} ) ) )".format( current_step, current_datetime ) )						

				self.on_step( current_datetime )

				self.lock_current_step( )
				
				current_step += 1
				self.set_current_step( current_step )			

				self.unlock_current_step( )

				self.log( '< Simulation step... done!' )							

			else:

				self._end_simulation( False )		

			simulator.send_sim_data_to_clients( )

			time.sleep( sim_sampling_rate / 1000 )	
							
		self.log_main( 'Simulating... done!' )	

	def on_step( self, current_datetime ):

		if self.can_simulate_new_actions( ):

			current_datetime_str = current_datetime.strftime( '%Y%m%d%H' )

			if current_datetime_str in self._affluence_counts:

				pass
			
			else:

				current_hour_of_day = current_datetime.hour
				affluence_url = "travel/affluence/{}".format( current_hour_of_day )
				affluence_res = self.fetch_gateway( affluence_url )
				affluence = int( affluence_res[ 'affluence' ] )
				self._affluence_counts[ current_datetime_str ] = affluence			

			if self._affluence_counts[ current_datetime_str ] > 0:		

				simulator = self._simulator

				for c in self._cars:

					c.lock( )

					car_can_travel = ( simulator.is_simulation_running( ) and not c.is_busy( ) )		
					if car_can_travel:
						c.start_travel( )	
						self._affluence_counts[ current_datetime_str ] -= 1	

					c.unlock( )

					if self._affluence_counts[ current_datetime_str ] < 1:						
						break					

		else:
			
			self.log( '-- Simulation period ended: this step is only used to resume travels and/or charging periods! --' )

	def can_simulate_new_actions( self ):
		simulator = self._simulator
		number_of_steps = simulator.get_config_by_key( 'number_of_steps' )
		can_simulate_new_actions = simulator.is_simulation_running( ) and ( self._current_step <= number_of_steps )
		return can_simulate_new_actions

	def lock_current_datetime( self ):
		caller = DebugHelper.get_caller( )
		self.log_debug( 'LOCKING DATETIME... (by {})'.format( caller ) )
		self._current_datetime_lock.acquire( )

	def unlock_current_datetime( self ):
		caller = DebugHelper.get_caller( )
		self.log_debug( 'UNLOCKING DATETIME... (by {})'.format( caller ) )
		self._current_datetime_lock.release( )

	def lock_current_step( self ):
		caller = DebugHelper.get_caller( )
		self.log_debug( 'LOCKING STEP... (by {})'.format( caller ) )
		self._current_step_lock.acquire( )

	def unlock_current_step( self ):
		caller = DebugHelper.get_caller( )
		self.log_debug( 'UNLOCKING STEP... (by {})'.format( caller ) )
		self._current_step_lock.release( )		

	def get_current_datetime( self ):
		return self._current_datetime

	def set_current_datetime( self, new_datetime ):
		self._current_datetime = new_datetime

	def get_current_step( self ):
		return self._current_step

	def set_current_step( self, new_step ):
		self._current_step = new_step				

	def _end_simulation( self, wait_for_thread ):
		simulator = self._simulator		
		simulator.set_simulation_state( False )

		for c in self._cars:
			c.destroy( )	

		if wait_for_thread:					
			self._thread.join( )

		simulator.send_sim_data_to_clients( )

	def log( self, message ):
		new_log = Log( self, message )
		self._logs.append( new_log )
		print( message )		

	def log_main( self, message ):
		self.log( '{} {}'.format( Simulation.MAIN_LOG_PREFIX, message ) ) 

	def log_debug( self, message ):
		simulator = self._simulator
		is_debug_enabled = simulator.get_config_by_key( 'enable_debug_mode' )
		if is_debug_enabled:
			self.log( message )

	def get_cars( self ):
		return self._cars

	def get_charging_plugs( self ):
		return self._charging_plugs

	def set_charging_plug_status( self, plug_id, plug_new_status ):
		plug = list( filter( lambda p : p.get_id( ) == plug_id, self._charging_plugs ) )
		plug = plug[ 0 ]
		plug.lock( )
		plug.set_status( plug_new_status )
		plug.unlock( )		

	def acquire_charging_plug( self ):
		caller = DebugHelper.get_caller( )		
		self.log_debug( 'ACQUIRING CHARGING PLUGS SEMAPHORE... (by {})'.format( caller ) )		
		self._charging_plugs_semaphore.acquire( )		

	def release_charging_plug( self ):
		caller = DebugHelper.get_caller( )			
		self.log_debug( 'RELEASING CHARGING PLUGS SEMAPHORE... (by {})'.format( caller ) )		
		self._charging_plugs_semaphore.release( )		

	def fetch_gateway( self, endpoint ):
		simulator = self._simulator

		base_url = simulator.get_config_by_key( 'gateway_request_base_url' )
		url = base_url.format( endpoint )
		response = requests.get( url )
		response_json = response.json( )
		self.log_debug( '\\\\\\ GATEWAY \\\\\\ URL: {}'.format( url )	 )
		self.log_debug( '\\\\\\ GATEWAY \\\\\\ RESPONSE: {}'.format( response_json ) )

		return response_json				
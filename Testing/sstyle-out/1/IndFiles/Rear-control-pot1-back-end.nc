( BEGIN FILE Rear-control-pot1-back-end.ncTNUM: -1 )
( Lefty:False Nunits:1 )
( cline: 9.733 delta:15.5 )
( start_unit: 1 num_units: 1)
( MOP:  Rear-control-pot1-back )
( FILE: G:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\s-in\Control\Rear-control-pot1-back.nc)
G90
(  BEGIN TOOL LIST )
(  TOOL 17 - Drawer slotting mill .25 - DESC: 1.2500 DIA, 2 FLUTE,  CARBIDE MAT )
(  ENDOF TOOL LIST )
( Rear-control-pot1-back)
( Whiteside 6805 drawer slot cutter pt25 kerf 1pt25 total diameter cut depth pt375 but use pt3 to be safe)
T17
S14000
M3
G0 Z4.0000
G0 X6.3816 Y-15.8356 
G1 X6.3816 Y-15.8356 Z1.2500 F75.
G1 X6.9816 Y-15.8356 Z1.2500 F20.
G1 X6.9816 Y-15.8356 Z0.2000
G1 X7.1316 Y-15.8356 Z0.2000
G1 X7.1316 Y-15.8356 Z1.2500
G1 X6.3816 Y-15.8356 Z1.2500
G0 Z4.0000
G0 X6.3816 Y-15.8356 
M5
G53 Z
G0 X2Y0
( END FILE Rear-control-pot1-back-end.nc )

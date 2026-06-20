( MOP:  Rear-control-pot2-back )
( FILE: G:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\s-in\Control\Rear-control-pot2-back.nc)
G90
(  BEGIN TOOL LIST )
(  TOOL 17 - Drawer slotting mill .25 - DESC: 1.2500 DIA, 2 FLUTE,  CARBIDE MAT )
(  ENDOF TOOL LIST )
( Rear-control-pot2-back)
( Whiteside 6805 drawer slot cutter pt25 kerf 1pt25 total diameter cut depth pt375 but use pt3 to be safe)
T17
S14000
M3
G0 Z4.0000
G0 X5.4747 Y-17.8031 
G1 X5.4747 Y-17.8031 Z1.2500 F75.
G1 X4.7247 Y-17.8031 Z1.2500 F20.
G1 X4.7247 Y-17.8031 Z0.2000
G1 X5.4747 Y-17.8031 Z0.2000
G0 Z4.0000
G0 X5.4747 Y-17.8031 
M5
G53 Z
X2Y0

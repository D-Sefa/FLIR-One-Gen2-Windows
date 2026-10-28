package com.dsefa.flir;

/** Suppress duplicate/denied requests, never persist a fictitious USB grant. */
public final class UsbPermissionGate {
    private String pending,denied;
    public boolean request(String device,boolean authorized){
        if(authorized)return false;
        if(pending!=null||device.equals(denied))return false;
        pending=device;return true;
    }
    public boolean finish(String device,boolean granted){
        if(device==null||!device.equals(pending))return false;
        pending=null;denied=granted?null:device;return true;
    }
    public void detached(String device){if(device.equals(pending))pending=null;if(device.equals(denied))denied=null;}
    public void retry(){denied=null;}
}

package com.dsefa.flir;
public final class PermissionTest {
    public static void main(String[] args){
        UsbPermissionGate g=new UsbPermissionGate();
        check(!g.request("camera-a",true),"already authorized must not prompt");
        check(g.request("camera-a",false),"new device requires system permission");
        check(!g.request("camera-a",false),"lifecycle/attach duplicate must not prompt twice");
        check(!g.finish("old-device",true),"stale callback must not authorize replacement");
        check(g.finish("camera-a",false),"matching denial must complete pending request");
        check(!g.request("camera-a",false),"denial must not create automatic prompt loop");
        g.retry();check(g.request("camera-a",false),"explicit Connect may retry denial");
        g.detached("camera-a");check(g.request("camera-b",false),"detach must clear pending identity");
        check(g.finish("camera-b",true),"matching grant must complete request");
        check(!g.request("camera-b",true),"actual system permission is authoritative");
        g.detached("camera-b");check(g.request("camera-b",false),"stored grant cannot bypass permission after unplug");
        System.out.println("PASS USB permission deduplication / denial / stale callback / reconnect");
    }
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}

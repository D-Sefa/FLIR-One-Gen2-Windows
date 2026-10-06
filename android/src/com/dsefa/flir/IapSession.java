package com.dsefa.flir;
import java.io.IOException;
import java.util.Arrays;

/** Host-side sequence translated from work/flir_iap2_frame.py. */
public final class IapSession {
    public interface Sender{void send(byte[] p)throws IOException;}
    public interface Starter{void start()throws IOException;}
    private final Sender sender;private final Starter starter;
    private final Protocol.Buffer control=new Protocol.Buffer();
    private boolean detected,syn,identified,started,pendingKeep;
    private int host=1,peer=0,transfer=1; private byte[] next;
    private long lastKeep;
    public IapSession(Sender s,Starter f){sender=s;starter=f;}
    public boolean streaming(){return started;}
    private void sendCsm(byte[] b)throws IOException{host=(host+1)&255;sender.send(Protocol.link(64,host,peer,1,b));}
    private void start()throws IOException{if(!started){starter.start();started=true;}}
    public void accept(byte[] p)throws IOException{accept(p,true);}
    public void accept(byte[] p,boolean newestData)throws IOException{
        if(Arrays.equals(p,Protocol.DETECT)){if(!detected){sender.send(p);detected=true;}return;}
        Protocol.Link l=Protocol.parseLink(p);if(l==null)return;
        if((l.control&64)!=0&&!syn){syn=true;host=l.ack;peer=l.seq;}
        if(l.control==128&&!syn){peer=l.seq;sender.send(Protocol.link(192,host,peer,0,l.payload));syn=true;return;}
        if(!syn||(l.control&64)==0)return;
        if(pendingKeep&&l.ack==host)pendingKeep=false;
        if(l.payload.length>0){peer=l.seq;
            if(newestData)sender.send(Protocol.link(64,host,peer,0,new byte[0]));
            if(l.session==2){start();return;}
            if(l.session!=1)return;
            control.add(l.payload,l.payload.length);
            while(control.length>=6){
                if(control.data[0]!=64||control.data[1]!=64){control.drop(1);continue;}
                int n=Protocol.be16(control.data,2);if(n<6){control.drop(1);continue;}if(n>control.length)break;
                byte[] c=control.take(n);int id=Protocol.csmId(c);
                if(id==0x1D01){sendCsm(Protocol.csm(0x1D02));next=Protocol.csm(0xAA00);}
                else if(id==0xAA01){byte[] challenge=new byte[20];for(int i=0;i<20;i++)challenge[i]=(byte)i;
                    sendCsm(Protocol.csm(0xAA02,new int[]{0},new byte[][]{challenge}));}
                else if(id==0xAA03){sendCsm(Protocol.csm(0xAA05));
                    next=Protocol.csm(0xEA00,new int[]{0,1},new byte[][]{new byte[]{0},new byte[]{0,2}});}
            }
        }else if(!identified&&l.ack==host){sendCsm(Protocol.csm(0x1D00));identified=true;}
        else if(next!=null&&l.ack==host){byte[] c=next;next=null;sendCsm(c);if(Protocol.csmId(c)==0xEA00)start();}
    }
    public void tick(long elapsedMs)throws IOException{
        if(started&&!pendingKeep&&elapsedMs-lastKeep>=30000){host=(host+1)&255;
            sender.send(Protocol.link(64,host,peer,2,Protocol.keepalive(transfer++&65535)));pendingKeep=true;lastKeep=elapsedMs;}
        if(pendingKeep&&elapsedMs-lastKeep>10000)throw new IOException("Config keepalive not acknowledged");
    }
}
